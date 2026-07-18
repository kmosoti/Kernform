"""Recorded catalog inspection and explicit generated-project version updates."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

from kernform.catalog import load_builtin_catalog
from kernform.errors import KernformPreconditionError
from kernform.generation import plan_adoption
from kernform.models import GitOptions, PlanResult, Profile, VersionCatalog, to_jsonable


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
    name, profile, capabilities, git = project_identity(canonical)
    return plan_adoption(
        canonical,
        name=name,
        profile=profile,
        capabilities=capabilities,
        git=git,
    )


def project_identity(root: Path) -> tuple[str, Profile, tuple[str, ...], GitOptions]:
    """Read the closed project identity needed for regeneration."""
    path = root / "kernform.toml"
    if not path.is_file():
        raise KernformPreconditionError(f"project manifest is missing: {path}")
    with path.open("rb") as source:
        document = cast(dict[str, object], tomllib.load(source))
    project_value = document.get("project")
    git_value = document.get("git")
    if not isinstance(project_value, dict) or not isinstance(git_value, dict):
        raise ValueError("project manifest identity tables are invalid")
    project = cast(dict[str, object], project_value)
    git_table = cast(dict[str, object], git_value)
    name = project.get("name")
    profile = project.get("profile")
    capabilities_value = project.get("capabilities")
    git_enabled = git_table.get("enabled")
    branch = git_table.get("initial_branch")
    capabilities_items = (
        cast(list[object], capabilities_value) if isinstance(capabilities_value, list) else []
    )
    if (
        not isinstance(name, str)
        or not isinstance(profile, str)
        or not all(isinstance(item, str) for item in capabilities_items)
        or not isinstance(git_enabled, bool)
        or not isinstance(branch, str)
    ):
        raise ValueError("project manifest identity values are invalid")
    return (
        name,
        Profile(profile),
        tuple(cast(list[str], capabilities_items)),
        GitOptions(enabled=git_enabled, initial_branch=branch),
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
