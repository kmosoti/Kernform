from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

import kernform
from kernform.errors import KernformPolicyError

ROOT = Path(__file__).resolve().parents[2]


def _run(argv: list[str], root: Path) -> None:
    subprocess.run(argv, cwd=root, check=True, capture_output=True, text=True)


def _generate(tmp_path: Path, signature: kernform.Signature) -> Path:
    name = f"sample-{signature.value}"
    root = tmp_path / name
    request = kernform.InitRequest(
        name=name,
        destination=root,
        signatures=(signature,),
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


def test_signature_manifests_match_public_contract() -> None:
    observed: set[str] = set()
    for signature in kernform.Signature:
        path = ROOT / "signatures" / signature.value / "signature.toml"
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        assert document["schema"] == "kernform.signature/v1"
        assert document["id"] == signature.value
        assert document["version"] == "1.0.0"
        observed.add(signature.value)
        resolution = kernform.resolve_project_signatures((signature,))
        assert signature in resolution.resolved
    assert observed == {signature.value for signature in kernform.Signature}


def test_combined_executables_require_and_honor_explicit_default() -> None:
    signatures = (kernform.Signature.CLI, kernform.Signature.DAEMON)
    with pytest.raises(KernformPolicyError, match="default_signature"):
        kernform.resolve_project_signatures(signatures)
    resolution = kernform.resolve_project_signatures(signatures, kernform.Signature.DAEMON)
    assert resolution.default_signature is kernform.Signature.DAEMON
    assert {kernform.Signature.SDK, *signatures} == set(resolution.resolved)


@pytest.mark.full
@pytest.mark.parametrize("signature", list(kernform.Signature))
def test_signatures_build_install_and_repeat(tmp_path: Path, signature: kernform.Signature) -> None:
    root = _generate(tmp_path, signature)
    if signature is kernform.Signature.INTERACTIVE_WEB:
        state = json.loads((root / ".kernform/state.json").read_text(encoding="utf-8"))
        owned_paths = {item["path"] for item in state["files"]}
        assert not any(Path(path).suffix in {".js", ".mjs", ".cjs"} for path in owned_paths)
    _build_install_and_test(root)
