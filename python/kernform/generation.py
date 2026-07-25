"""High-level deterministic profile generation over native planning and transactions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from kernform import _native
from kernform.api import apply_plan, inspect_repository, plan_initialization
from kernform.catalog import load_builtin_catalog
from kernform.models import (
    ApplyRequest,
    ApplyResult,
    GitOptions,
    InitRequest,
    Ownership,
    PlanRequest,
    PlanResult,
    Profile,
    RenderedFile,
    RepositorySnapshot,
    to_jsonable,
)

PROFILE_CAPABILITIES: dict[Profile, tuple[str, ...]] = {
    Profile.LIBRARY: (
        "pyo3-bindings",
        "testing",
        "locks-base",
        "ci",
        "release",
        "podman",
        "nushell-human",
        "nushell-agent",
    ),
    Profile.CLI: (
        "cli",
        "locks-base",
        "ci",
        "release",
        "podman",
        "nushell-human",
        "nushell-agent",
    ),
    Profile.API: (
        "api",
        "locks-api",
        "ci",
        "release",
        "podman",
        "nushell-human",
        "nushell-agent",
    ),
}


def plan_project(
    *,
    name: str,
    profile: Profile,
    capabilities: tuple[str, ...] = (),
    git: GitOptions | None = None,
    snapshot: RepositorySnapshot | None = None,
) -> PlanResult:
    """Compose capabilities and return an immutable native plan."""
    git = git or GitOptions()
    requested = tuple(sorted(set(PROFILE_CAPABILITIES[profile]) | set(capabilities)))
    if "web-server" in requested and profile is not Profile.API:
        raise ValueError("web-server is supported only by the api profile")
    catalog = load_builtin_catalog()
    module_name = name.replace("-", "_")
    variables = _variables(
        name, module_name, profile, requested, git, catalog.versions, catalog.images
    )
    files = _rendered_files(requested, variables)
    return plan_initialization(
        PlanRequest(
            name=name,
            profile=profile,
            capabilities=requested,
            git=git,
            snapshot=snapshot or RepositorySnapshot.empty(),
            catalog=catalog,
            files=files,
        )
    )


def initialize_project(request: InitRequest) -> ApplyResult:
    """Plan and atomically publish a new complete project."""
    if request.destination.exists():
        plan = plan_adoption(
            request.destination,
            name=request.name,
            profile=request.profile,
            capabilities=request.capabilities,
            git=request.git,
        )
        return apply_adoption(request.destination, plan)
    plan = plan_project(
        name=request.name,
        profile=request.profile,
        capabilities=request.capabilities,
        git=request.git,
    )
    return apply_plan(ApplyRequest(request.destination, plan, new_project=True))


def plan_adoption(
    root: Path,
    *,
    name: str,
    profile: Profile,
    capabilities: tuple[str, ...] = (),
    git: GitOptions | None = None,
) -> PlanResult:
    """Plan an ownership-aware adoption against the live snapshot."""
    git = git or GitOptions()
    state_path = root / ".kernform/state.json"
    state_json = state_path.read_text(encoding="utf-8") if state_path.is_file() else None
    snapshot = inspect_repository(root, state_json)
    return plan_project(
        name=name,
        profile=profile,
        capabilities=capabilities,
        git=git,
        snapshot=snapshot,
    )


def apply_adoption(root: Path, plan: PlanResult) -> ApplyResult:
    """Apply one confirmed adoption plan."""
    return apply_plan(ApplyRequest(root, plan, new_project=False))


def _rendered_files(
    requested: tuple[str, ...], variables: dict[str, str]
) -> tuple[RenderedFile, ...]:
    raw: object = json.loads(_native.render_capabilities_json(_json(requested), _json(variables)))
    if not isinstance(raw, list):
        raise ValueError("native capability renderer did not return an array")
    files: list[RenderedFile] = []
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            raise ValueError("native capability renderer returned an invalid file")
        value = cast(dict[str, object], item)
        path = value.get("path")
        content = value.get("content")
        ownership = value.get("ownership")
        if (
            not isinstance(path, str)
            or not isinstance(content, str)
            or not isinstance(ownership, str)
        ):
            raise ValueError("native capability renderer returned invalid file fields")
        files.append(RenderedFile(path, content, Ownership(ownership)))
    return tuple(files)


def _variables(
    name: str,
    module_name: str,
    profile: Profile,
    capabilities: tuple[str, ...],
    git: GitOptions,
    versions: dict[str, str],
    images: dict[str, str],
) -> dict[str, str]:
    runtime_entrypoint = (
        f'"python", "-c", "import {module_name}; print({module_name}.native_version())"'
    )
    agent_entrypoint = runtime_entrypoint
    if profile is Profile.CLI:
        runtime_entrypoint = f'"{name}", "20", "22", "--agent"'
        agent_entrypoint = f'"python", "-m", "{module_name}.cli"'
    elif profile is Profile.API:
        app_module = "web" if "web-server" in capabilities else "app"
        runtime_entrypoint = (
            f'"granian", "--interface", "asgi", "{module_name}.{app_module}:app", '
            '"--host", "0.0.0.0", "--port", "8000"'
        )
    capability_list = ", ".join(f'"{item}"' for item in capabilities)
    result = {
        "project_name": name,
        "module_name": module_name,
        "profile": str(profile),
        "capability_list": capability_list,
        "git_enabled": "true" if git.enabled else "false",
        "catalog_id": load_builtin_catalog().id,
        "catalog_hash": load_builtin_catalog().hash,
        "catalog_resolved_at": load_builtin_catalog().resolved_at,
        "catalog_source": load_builtin_catalog().source,
        "python_version": versions["python"],
        "python_minimum": ".".join(versions["python"].split(".")[:2]),
        "rust_version": versions["rust"],
        "maturin_version": versions["maturin"],
        "pyo3_version": versions["pyo3"],
        "pyright_version": versions["pyright"],
        "pytest_version": versions["pytest"],
        "ruff_version": versions["ruff"],
        "uv_version": versions["uv"],
        "python_image_digest": images["python-slim-linux-amd64"],
        "rust_image_digest": images["rust-slim-linux-amd64"],
        "runtime_entrypoint": runtime_entrypoint,
        "agent_entrypoint": agent_entrypoint,
    }
    result.update({f"version_{name.replace('-', '_')}": value for name, value in versions.items()})
    return result


def _json(value: object) -> str:
    return json.dumps(to_jsonable(value), sort_keys=True, separators=(",", ":"))
