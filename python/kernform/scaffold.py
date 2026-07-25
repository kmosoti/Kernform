"""Bounded ownership-aware scaffold planning for managed projects."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import cast

from kernform.api import apply_plan, inspect_repository, plan_initialization
from kernform.catalog import load_builtin_catalog
from kernform.errors import KernformPolicyError, KernformPreconditionError
from kernform.models import (
    ApplyRequest,
    ApplyResult,
    GitOptions,
    Ownership,
    PlanRequest,
    Profile,
    RenderedFile,
)

_MODULE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def scaffold_module(root: Path, kind: str, name: str) -> ApplyResult:
    """Add one seeded Python module through the normal plan/apply transaction."""
    canonical = root.resolve(strict=True)
    if kind != "module":
        raise KernformPolicyError(
            f"unsupported scaffold kind {kind!r}; Kernform 0.1.0 supports only 'module'"
        )
    if _MODULE_NAME.fullmatch(name) is None:
        raise KernformPolicyError("module name must match ^[a-z][a-z0-9_]{0,62}$")
    manifest_path = canonical / "kernform.toml"
    state_path = canonical / ".kernform/state.json"
    if not manifest_path.is_file() or not state_path.is_file():
        raise KernformPreconditionError("scaffold requires a managed Kernform project")
    with manifest_path.open("rb") as source:
        manifest = cast(dict[str, object], tomllib.load(source))
    project_value = manifest.get("project")
    if not isinstance(project_value, dict):
        raise KernformPolicyError("project manifest has no project table")
    project = cast(dict[str, object], project_value)
    project_name = project.get("name")
    profile_value = project.get("profile")
    capabilities_value = project.get("capabilities")
    capabilities_items = (
        cast(list[object], capabilities_value) if isinstance(capabilities_value, list) else []
    )
    if (
        not isinstance(project_name, str)
        or not isinstance(profile_value, str)
        or not isinstance(capabilities_value, list)
        or not all(isinstance(item, str) for item in capabilities_items)
    ):
        raise KernformPolicyError("project manifest identity fields are invalid")
    capabilities = tuple(cast(list[str], capabilities_items))
    module_name = project_name.replace("-", "_")
    destination = f"python/{module_name}/{name}.py"
    content = (
        f'"""Seeded {name} module; user edits are preserved by Kernform."""\n\n'
        "from __future__ import annotations\n\n\n"
        "def run() -> dict[str, str]:\n"
        f'    """Return the scaffold identity."""\n    return {{"module": "{name}"}}\n'
    )
    snapshot = inspect_repository(canonical, state_path.read_text(encoding="utf-8"))
    plan = plan_initialization(
        PlanRequest(
            name=project_name,
            profile=Profile(profile_value),
            capabilities=capabilities,
            git=GitOptions(enabled=False),
            snapshot=snapshot,
            catalog=load_builtin_catalog(),
            files=(RenderedFile(destination, content, Ownership.SEEDED),),
        )
    )
    return apply_plan(ApplyRequest(canonical, plan, new_project=False))
