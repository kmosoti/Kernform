"""Recorded catalog inspection and explicit generated-project version updates."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

from kernform.catalog import load_builtin_catalog
from kernform.generation import plan_adoption
from kernform.models import GitOptions, PlanResult, Signature, VersionCatalog, to_jsonable
from kernform.project_form import read_project_form


def inspect_version_state(root: Path) -> dict[str, object]:
    """Return expected and recorded exact catalog state."""
    canonical = root.resolve(strict=True)
    expected = load_builtin_catalog()
    recorded = _recorded_lock(canonical)
    differences = _differences(expected, recorded, canonical)
    return {
        "catalog": to_jsonable(expected),
        "recorded": recorded,
        "conformant": not differences,
        "differences": differences,
    }


def plan_version_update(root: Path) -> PlanResult:
    """Produce the normal immutable adoption plan against the built-in catalog."""
    canonical = root.resolve(strict=True)
    name, signatures, default_signature, capabilities, git = project_identity(canonical)
    return plan_adoption(
        canonical,
        name=name,
        signatures=signatures,
        default_signature=default_signature,
        capabilities=capabilities,
        git=git,
    )


def project_identity(
    root: Path,
) -> tuple[str, tuple[Signature, ...], Signature | None, tuple[str, ...], GitOptions]:
    """Read the closed project identity needed for regeneration."""
    form = read_project_form(root)
    return (
        form.name,
        form.signatures,
        form.default_signature,
        form.capabilities,
        form.git,
    )


def _recorded_lock(root: Path) -> dict[str, object] | None:
    path = root / ".kernform/toolchains.lock.toml"
    if not path.is_file():
        return None
    with path.open("rb") as source:
        return cast(dict[str, object], tomllib.load(source))


def _differences(
    expected: VersionCatalog,
    recorded: dict[str, object] | None,
    root: Path,
) -> list[str]:
    if recorded is None:
        return ["missing .kernform/toolchains.lock.toml"]
    differences: list[str] = []
    if recorded.get("catalog_id") != expected.id:
        differences.append("catalog_id")
    if recorded.get("catalog_hash") != expected.hash:
        differences.append("catalog_hash")
    tools_value = recorded.get("tools")
    images_value = recorded.get("images")
    tools = cast(dict[str, object], tools_value) if isinstance(tools_value, dict) else {}
    images = cast(dict[str, object], images_value) if isinstance(images_value, dict) else {}
    if tools != expected.versions:
        differences.append("tools")
    if images != expected.images:
        differences.append("images")
    for lock in ("Cargo.lock", "uv.lock"):
        if not (root / lock).is_file():
            differences.append(f"missing {lock}")
    return differences
