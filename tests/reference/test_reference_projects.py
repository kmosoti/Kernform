from __future__ import annotations

from pathlib import Path

import pytest

import kernform

ROOT = Path(__file__).resolve().parents[2]
CASES = (
    ("sdk", "example-sdk", kernform.Signature.SDK),
    ("cli", "example-cli", kernform.Signature.CLI),
    ("api", "example-api", kernform.Signature.API),
    ("interactive-web", "example-interactive-web", kernform.Signature.INTERACTIVE_WEB),
    ("daemon", "example-daemon", kernform.Signature.DAEMON),
)


def _files(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts[:2] == (".kernform", "transactions"):
            continue
        files[relative.as_posix()] = path.read_bytes()
    return files


@pytest.mark.full
@pytest.mark.parametrize(("directory", "name", "signature"), CASES)
def test_reference_project_matches_fresh_generator_output(
    tmp_path: Path,
    directory: str,
    name: str,
    signature: kernform.Signature,
) -> None:
    generated = tmp_path / directory
    kernform.initialize_project(
        kernform.InitRequest(
            name=name,
            destination=generated,
            signatures=(signature,),
            git=kernform.GitOptions(enabled=False),
        )
    )
    assert _files(ROOT / "reference" / directory) == _files(generated)


def test_reference_web_surface_contains_no_javascript_or_node() -> None:
    root = ROOT / "reference/interactive-web"
    paths = set(_files(root))
    assert "package.json" not in paths
    assert not any(Path(path).suffix in {".js", ".mjs", ".cjs"} for path in paths)
    assert (
        "<script"
        not in (root / "python/example_interactive_web/templates/index.html")
        .read_text(encoding="utf-8")
        .lower()
    )
