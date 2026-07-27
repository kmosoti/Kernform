"""High-level deterministic signature generation over native planning and transactions."""

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
    RenderedFile,
    RepositorySnapshot,
    Signature,
    SignatureResolution,
    to_jsonable,
)


def plan_project(
    *,
    name: str,
    signatures: tuple[Signature, ...] = (Signature.SDK,),
    default_signature: Signature | None = None,
    capabilities: tuple[str, ...] = (),
    git: GitOptions | None = None,
    snapshot: RepositorySnapshot | None = None,
) -> PlanResult:
    """Compose capabilities and return an immutable native plan."""
    git = git or GitOptions()
    resolution = resolve_project_signatures(signatures, default_signature)
    requested = tuple(sorted(set(resolution.capabilities) | set(capabilities)))
    catalog = load_builtin_catalog()
    module_name = name.replace("-", "_")
    variables = _variables(
        name, module_name, resolution, requested, git, catalog.versions, catalog.images
    )
    files = _rendered_files(requested, variables)
    return plan_initialization(
        PlanRequest(
            name=name,
            requested_signatures=resolution.requested,
            resolved_signatures=resolution.resolved,
            default_signature=resolution.default_signature,
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
            signatures=request.signatures,
            default_signature=request.default_signature,
            capabilities=request.capabilities,
            git=request.git,
        )
        return apply_adoption(request.destination, plan)
    plan = plan_project(
        name=request.name,
        signatures=request.signatures,
        default_signature=request.default_signature,
        capabilities=request.capabilities,
        git=request.git,
    )
    return apply_plan(ApplyRequest(request.destination, plan, new_project=True))


def plan_adoption(
    root: Path,
    *,
    name: str,
    signatures: tuple[Signature, ...] = (Signature.SDK,),
    default_signature: Signature | None = None,
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
        signatures=signatures,
        default_signature=default_signature,
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


def resolve_project_signatures(
    signatures: tuple[Signature, ...],
    default_signature: Signature | None = None,
) -> SignatureResolution:
    """Resolve signature implication and runtime selection in the native kernel."""
    raw: object = json.loads(
        _native.resolve_signatures_json(_json(signatures), _json(default_signature))
    )
    if not isinstance(raw, dict):
        raise ValueError("native signature resolver did not return an object")
    value = cast(dict[str, object], raw)
    requested = value.get("requested")
    resolved = value.get("resolved")
    capabilities = value.get("capabilities")
    runtime = value.get("default_signature")
    requested_items = _string_tuple(requested, "requested")
    resolved_items = _string_tuple(resolved, "resolved")
    capability_items = _string_tuple(capabilities, "capabilities")
    if runtime is not None and not isinstance(runtime, str):
        raise ValueError("native signature resolver returned invalid fields")
    return SignatureResolution(
        requested=tuple(Signature(item) for item in requested_items),
        resolved=tuple(Signature(item) for item in resolved_items),
        capabilities=capability_items,
        default_signature=Signature(runtime) if isinstance(runtime, str) else None,
    )


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"native signature resolver returned invalid {label}")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise ValueError(f"native signature resolver returned invalid {label}")
    return tuple(cast(list[str], items))


def _variables(
    name: str,
    module_name: str,
    resolution: SignatureResolution,
    capabilities: tuple[str, ...],
    git: GitOptions,
    versions: dict[str, str],
    images: dict[str, str],
) -> dict[str, str]:
    runtime_entrypoint = (
        f'"python", "-c", "import {module_name}; print({module_name}.native_version())"'
    )
    agent_entrypoint = runtime_entrypoint
    if resolution.default_signature is Signature.CLI:
        runtime_entrypoint = f'"{name}", "20", "22", "--agent"'
        agent_entrypoint = f'"python", "-m", "{module_name}.cli"'
    elif resolution.default_signature in (Signature.API, Signature.INTERACTIVE_WEB):
        app_module = "web" if resolution.default_signature is Signature.INTERACTIVE_WEB else "app"
        runtime_entrypoint = (
            f'"granian", "--interface", "asgi", "{module_name}.{app_module}:app", '
            '"--host", "0.0.0.0", "--port", "8000"'
        )
    elif resolution.default_signature is Signature.DAEMON:
        runtime_entrypoint = f'"python", "-m", "{module_name}.daemon"'
        agent_entrypoint = runtime_entrypoint
    capability_list = ", ".join(f'"{item}"' for item in capabilities)
    requested_signature_list = ", ".join(f'"{item}"' for item in resolution.requested)
    resolved_signature_list = ", ".join(f'"{item}"' for item in resolution.resolved)
    runtime_default_line = (
        f'default_signature = "{resolution.default_signature}"'
        if resolution.default_signature is not None
        else ""
    )
    result = {
        "project_name": name,
        "module_name": module_name,
        "requested_signature_list": requested_signature_list,
        "resolved_signature_list": resolved_signature_list,
        "runtime_default_line": runtime_default_line,
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
