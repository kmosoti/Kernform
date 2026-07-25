"""Typed public operations backed by the private native adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from kernform import _native
from kernform.models import (
    ApplyRequest,
    ApplyResult,
    Ownership,
    PlanRequest,
    PlanResult,
    ReleasePhase,
    ReleaseState,
    RepositorySnapshot,
    SnapshotFile,
    to_jsonable,
)


def version() -> str:
    """Return the native Kernform version."""
    return _native.native_version()


def plan_initialization(request: PlanRequest) -> PlanResult:
    """Produce an immutable plan without performing effects."""
    intent = {
        "name": request.name,
        "profile": request.profile,
        "capabilities": sorted(request.capabilities),
        "git": request.git,
    }
    return PlanResult(
        _native.plan_initialization_json(
            _json(intent),
            _json(request.snapshot),
            _json(request.catalog),
            _json(request.files),
        )
    )


def apply_plan(request: ApplyRequest) -> ApplyResult:
    """Apply a plan transactionally to a new or existing project root."""
    raw = _object(
        _native.apply_plan_json(str(request.root), request.plan.json, request.new_project)
    )
    plan_id = raw.get("plan_id")
    operation_count = raw.get("operation_count")
    state_path = raw.get("state_path")
    if (
        not isinstance(plan_id, str)
        or not isinstance(operation_count, int)
        or not isinstance(state_path, str)
    ):
        raise ValueError("native apply result has an invalid shape")
    return ApplyResult(plan_id, operation_count, Path(state_path))


def inspect_repository(root: Path, state_json: str | None = None) -> RepositorySnapshot:
    """Inspect a project directory without following symlinks or reading Git internals."""
    raw = _object(_native.inspect_repository_json(str(root), state_json))
    files_value = raw.get("files")
    if not isinstance(files_value, dict):
        raise ValueError("native repository snapshot has no files object")
    files: dict[str, SnapshotFile] = {}
    for path, value in cast(dict[object, object], files_value).items():
        if not isinstance(path, str) or not isinstance(value, dict):
            raise ValueError("native repository snapshot contains an invalid file entry")
        entry = cast(dict[object, object], value)
        digest = entry.get("hash")
        ownership_value = entry.get("ownership")
        if not isinstance(digest, str) or not (
            ownership_value is None or isinstance(ownership_value, str)
        ):
            raise ValueError("native repository snapshot contains invalid file metadata")
        ownership = Ownership(ownership_value) if ownership_value is not None else None
        files[path] = SnapshotFile(digest, ownership)
    exists = raw.get("exists")
    git = raw.get("git")
    branch = raw.get("primary_branch")
    if not isinstance(exists, bool) or not isinstance(git, bool):
        raise ValueError("native repository snapshot has invalid flags")
    if branch is not None and not isinstance(branch, str):
        raise ValueError("native repository snapshot has an invalid branch")
    return RepositorySnapshot(exists, git, branch, files)


def check_web_policy(files: tuple[object, ...]) -> list[dict[str, object]]:
    """Evaluate rendered resources against the no-JavaScript policy."""
    value: object = json.loads(_native.check_web_policy_json(_json(files)))
    if not isinstance(value, list):
        raise ValueError("native diagnostics result has an invalid shape")
    items = cast(list[object], value)
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("native diagnostics result has an invalid shape")
    return [cast(dict[str, object], item) for item in items]


def git_initial_commit(root: Path, message: str = "Initial commit") -> str:
    """Create an explicitly requested initial commit after Git policy validation."""
    return _native.git_initial_commit_json(str(root), message)


def release_start(root: Path, release_version: str, catalog_hash: str) -> ReleaseState:
    """Start a local release branch from clean committed main."""
    return _release_state(_native.release_start_json(str(root), release_version, catalog_hash))


def release_inspect(root: Path) -> ReleaseState:
    """Inspect persisted local release state."""
    return _release_state(_native.release_inspect_json(str(root)))


def release_verify(
    root: Path,
    *,
    metadata_matches: bool,
    synchronized: bool,
) -> ReleaseState:
    """Verify local release source and metadata evidence."""
    return _release_state(_native.release_verify_json(str(root), metadata_matches, synchronized))


def release_finalize(root: Path, *, verification_complete: bool) -> ReleaseState:
    """Finalize local state without creating a tag or publishing."""
    return _release_state(_native.release_finalize_json(str(root), verification_complete))


def _json(value: object) -> str:
    return json.dumps(to_jsonable(value), sort_keys=True, separators=(",", ":"))


def _object(raw: str) -> dict[str, object]:
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("native result is not an object")
    return cast(dict[str, object], value)


def _release_state(raw: str) -> ReleaseState:
    value = _object(raw)
    release_version = value.get("version")
    branch = value.get("branch")
    source_commit = value.get("source_commit")
    catalog_hash = value.get("catalog_hash")
    phase = value.get("phase")
    if not all(
        isinstance(item, str)
        for item in (release_version, branch, source_commit, catalog_hash, phase)
    ):
        raise ValueError("native release state has an invalid shape")
    return ReleaseState(
        cast(str, release_version),
        cast(str, branch),
        cast(str, source_commit),
        cast(str, catalog_hash),
        ReleasePhase(cast(str, phase)),
    )
