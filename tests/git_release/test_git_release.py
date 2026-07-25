from __future__ import annotations

import subprocess
from pathlib import Path

import kernform
from kernform.catalog import load_builtin_catalog


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_local_git_and_release_flow_updates_metadata_without_tag_or_remote(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example"
    kernform.initialize_project(kernform.InitRequest(name="example", destination=root))
    assert _git(root, "symbolic-ref", "--short", "HEAD") == "main"
    assert _git(root, "remote") == ""
    assert (
        subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=root, capture_output=True
        ).returncode
        != 0
    )

    _git(root, "config", "user.name", "Kernform Test")
    _git(root, "config", "user.email", "kernform@example.invalid")
    initial = kernform.git_initial_commit(root)
    assert initial == _git(root, "rev-parse", "HEAD")
    assert _git(root, "status", "--porcelain=v1") == ""

    started = kernform.release_start(root, "0.2.0", load_builtin_catalog().hash)
    assert started.branch == "release/0.2.0"
    assert _git(root, "branch", "--show-current") == "release/0.2.0"
    assert 'version = "0.2.0"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.2.0"' in (root / "Cargo.toml").read_text(encoding="utf-8")
    assert "0.2.0" in (root / "Cargo.lock").read_text(encoding="utf-8")
    assert "0.2.0" in (root / "uv.lock").read_text(encoding="utf-8")

    _git(root, "add", "--all")
    _git(root, "commit", "-m", "Prepare 0.2.0")
    verified = kernform.release_verify(root, metadata_matches=True, synchronized=True)
    assert verified.phase is kernform.ReleasePhase.VERIFIED
    finalized = kernform.release_finalize(root, verification_complete=True)
    assert finalized.phase is kernform.ReleasePhase.FINALIZED
    assert _git(root, "tag", "--list") == ""
    assert _git(root, "remote") == ""
