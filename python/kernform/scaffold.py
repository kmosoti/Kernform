"""Bounded ownership-aware scaffold planning for managed projects."""

from __future__ import annotations

import re
from pathlib import Path

from kernform.api import apply_plan, inspect_repository, plan_initialization
from kernform.catalog import load_builtin_catalog
from kernform.errors import KernformPolicyError, KernformPreconditionError
from kernform.generation import resolve_project_signatures
from kernform.models import (
    ApplyRequest,
    ApplyResult,
    GitOptions,
    Ownership,
    PlanRequest,
    RenderedFile,
)
from kernform.project_form import read_project_form

_MODULE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def scaffold_module(root: Path, kind: str, name: str) -> ApplyResult:
    """Add one seeded Python module through the normal plan/apply transaction."""
    canonical = root.resolve(strict=True)
    if kind != "module":
        raise KernformPolicyError(
            f"unsupported scaffold kind {kind!r}; Kernform 0.2.0 supports only 'module'"
        )
    if _MODULE_NAME.fullmatch(name) is None:
        raise KernformPolicyError("module name must match ^[a-z][a-z0-9_]{0,62}$")
    manifest_path = canonical / "kernform.toml"
    state_path = canonical / ".kernform/state.json"
    if not manifest_path.is_file() or not state_path.is_file():
        raise KernformPreconditionError("scaffold requires a managed Kernform project")
    form = read_project_form(canonical)
    resolution = resolve_project_signatures(form.signatures, form.default_signature)
    project_name = form.name
    capabilities = form.capabilities
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
            requested_signatures=resolution.requested,
            resolved_signatures=resolution.resolved,
            default_signature=resolution.default_signature,
            capabilities=capabilities,
            git=GitOptions(enabled=False),
            snapshot=snapshot,
            catalog=load_builtin_catalog(),
            files=(RenderedFile(destination, content, Ownership.SEEDED),),
        )
    )
    return apply_plan(ApplyRequest(canonical, plan, new_project=False))
