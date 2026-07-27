from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import cast

import pytest

from kernform.release_artifacts import build_release_bundle, verify_release_bundle

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
ACTION_PIN = re.compile(r"uses:\s+[^@\s]+@([0-9a-f]{40})(?:\s+#.*)?$")


def test_workflows_pin_actions_and_do_not_use_privileged_pull_requests() -> None:
    paths = [WORKFLOWS / name for name in ("ci.yml", "nightly.yml")]
    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert "pull_request_target" not in content
        uses_lines = [line.strip() for line in content.splitlines() if "uses:" in line]
        assert uses_lines
        assert all(ACTION_PIN.search(line) for line in uses_lines)
        assert "persist-credentials: false" in content


def test_ci_is_read_only_and_fork_safe() -> None:
    content = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in content
    assert "secrets." not in content
    assert "uv sync --all-groups --frozen" in content
    assert "kernform --agent test fast" in content


def test_release_bundle_is_byte_stable_and_self_verifying(tmp_path: Path) -> None:
    root = tmp_path / "source"
    wheel_directory = root / "wheels"
    (root / "fixtures/catalogs").mkdir(parents=True)
    wheel_directory.mkdir()
    (root / "Cargo.lock").write_text("version = 4\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (root / "fixtures/catalogs/stable-v1.json").write_text(
        '{"catalog":{"hash":"' + "1" * 64 + '"}}\n', encoding="utf-8"
    )
    (wheel_directory / "kernform-0.1.0-py3-none-any.whl").write_bytes(b"wheel-bytes")
    (wheel_directory / "kernform-0.1.0.tar.gz").write_bytes(b"sdist-bytes")
    (wheel_directory / "kernform-0.1.0-oci.tar").write_bytes(b"oci-bytes")
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_NAME": "Kernform Test",
            "GIT_AUTHOR_EMAIL": "kernform@example.invalid",
            "GIT_COMMITTER_NAME": "Kernform Test",
            "GIT_COMMITTER_EMAIL": "kernform@example.invalid",
            "GIT_AUTHOR_DATE": "2026-07-17T12:00:00Z",
            "GIT_COMMITTER_DATE": "2026-07-17T12:00:00Z",
        }
    )
    subprocess.run(
        ["git", "commit", "-m", "release input"],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
    )
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()

    first = build_release_bundle(
        root,
        version="0.1.0",
        source_commit=source_commit,
        wheel_directory=wheel_directory,
        output_directory=tmp_path / "first",
    )
    second = build_release_bundle(
        root,
        version="0.1.0",
        source_commit=source_commit,
        wheel_directory=wheel_directory,
        output_directory=tmp_path / "second",
    )
    assert first.read_bytes() == second.read_bytes()
    result = verify_release_bundle(first)
    assert result["schema"] == "kernform.release-bundle/v1"
    entries_value = result["entries"]
    assert isinstance(entries_value, list)
    entries = cast(list[object], entries_value)
    assert "metadata/sbom.spdx.json" in entries
    assert "metadata/provenance.intoto.json" in entries

    with pytest.raises(ValueError, match="wheel version"):
        build_release_bundle(
            root,
            version="0.2.0",
            source_commit=source_commit,
            wheel_directory=wheel_directory,
            output_directory=tmp_path / "wrong-version",
        )

    (root / "Cargo.lock").write_text("version = 5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="uncommitted tracked changes"):
        build_release_bundle(
            root,
            version="0.1.0",
            source_commit=source_commit,
            wheel_directory=wheel_directory,
            output_directory=tmp_path / "dirty-source",
        )

    subprocess.run(["git", "add", "Cargo.lock"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "new source"],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
    )
    with pytest.raises(ValueError, match="checked-out HEAD"):
        build_release_bundle(
            root,
            version="0.1.0",
            source_commit=source_commit,
            wheel_directory=wheel_directory,
            output_directory=tmp_path / "wrong-head",
        )
