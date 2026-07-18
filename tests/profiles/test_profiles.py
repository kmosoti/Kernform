from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

import kernform
from kernform.generation import PROFILE_CAPABILITIES

ROOT = Path(__file__).resolve().parents[2]


def _run(argv: list[str], root: Path) -> None:
    subprocess.run(argv, cwd=root, check=True, capture_output=True, text=True)


def _generate(tmp_path: Path, profile: kernform.Profile, *, web: bool = False) -> Path:
    name = f"sample-{profile.value}"
    root = tmp_path / name
    capabilities = ("web-server",) if web else ()
    request = kernform.InitRequest(
        name=name,
        destination=root,
        profile=profile,
        capabilities=capabilities,
    )
    first = kernform.initialize_project(request)
    assert first.operation_count > 0

    branch = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    remotes = subprocess.run(
        ["git", "remote"], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert branch == "main"
    assert remotes == ""
    assert head.returncode != 0

    second = kernform.initialize_project(request)
    assert second.operation_count == 0
    assert (root / "Cargo.lock").is_file()
    assert (root / "uv.lock").is_file()
    return root


def _build_install_and_test(root: Path) -> None:
    _run(["cargo", "test", "--workspace", "--locked"], root)
    _run(["uv", "sync", "--all-groups", "--frozen"], root)
    _run(["uv", "run", "pytest"], root)


def test_profile_manifests_match_public_composition() -> None:
    for profile, expected in PROFILE_CAPABILITIES.items():
        path = ROOT / "profiles" / profile.value / "profile.toml"
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        assert document == {
            "schema": "kernform.profile/v1",
            "id": profile.value,
            "capabilities": list(expected),
        }


@pytest.mark.full
@pytest.mark.parametrize("profile", [kernform.Profile.LIBRARY, kernform.Profile.CLI])
def test_library_or_cli_profiles_build_install_and_repeat(
    tmp_path: Path, profile: kernform.Profile
) -> None:
    _build_install_and_test(_generate(tmp_path, profile))


@pytest.mark.full
@pytest.mark.parametrize("web", [False, True], ids=["api", "api-web"])
def test_api_profiles_build_install_and_repeat(tmp_path: Path, web: bool) -> None:
    root = _generate(tmp_path, kernform.Profile.API, web=web)
    if web:
        state = json.loads((root / ".kernform/state.json").read_text(encoding="utf-8"))
        owned_paths = {item["path"] for item in state["files"]}
        assert not any(Path(path).suffix in {".js", ".mjs", ".cjs"} for path in owned_paths)
    _build_install_and_test(root)
