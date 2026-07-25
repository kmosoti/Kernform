"""Typed public request and result models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast


class Profile(StrEnum):
    """Frozen 0.1.0 project profiles."""

    LIBRARY = "library"
    CLI = "cli"
    API = "api"


class Ownership(StrEnum):
    """Frozen v1 file ownership values."""

    MANAGED = "managed"
    SEEDED = "seeded"
    GENERATED = "generated"
    USER = "user"
    EXTERNAL = "external"


class ReleasePhase(StrEnum):
    """Pure local release-flow phases."""

    IDLE = "idle"
    STARTED = "started"
    VERIFIED = "verified"
    FINALIZED = "finalized"


@dataclass(frozen=True, slots=True)
class GitOptions:
    """Local Git initialization intent."""

    enabled: bool = True
    initial_branch: str = "main"
    initial_commit: bool = False


@dataclass(frozen=True, slots=True)
class SnapshotFile:
    """Observed file hash and ownership."""

    hash: str
    ownership: Ownership | None


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    """Side-effect-free repository observation."""

    exists: bool
    git: bool
    primary_branch: str | None
    files: dict[str, SnapshotFile]

    @classmethod
    def empty(cls) -> RepositorySnapshot:
        """Return the absent-repository snapshot used for new initialization."""
        return cls(exists=False, git=False, primary_branch=None, files={})


@dataclass(frozen=True, slots=True)
class VersionCatalog:
    """Exact immutable version catalog."""

    id: str
    hash: str
    resolved_at: str
    source: str
    versions: dict[str, str]
    images: dict[str, str]


@dataclass(frozen=True, slots=True)
class RenderedFile:
    """Fully rendered input to pure planning."""

    path: str
    content: str
    ownership: Ownership


@dataclass(frozen=True, slots=True)
class PlanRequest:
    """Typed pure-planning request."""

    name: str
    profile: Profile
    capabilities: tuple[str, ...]
    git: GitOptions
    snapshot: RepositorySnapshot
    catalog: VersionCatalog
    files: tuple[RenderedFile, ...]


@dataclass(frozen=True, slots=True)
class InitRequest:
    """High-level project initialization request."""

    name: str
    destination: Path
    profile: Profile = Profile.LIBRARY
    capabilities: tuple[str, ...] = ()
    git: GitOptions = GitOptions()


@dataclass(frozen=True, slots=True)
class PlanResult:
    """Validated native plan document retained byte-for-byte for apply."""

    json: str

    @property
    def document(self) -> dict[str, object]:
        """Decode the plan as an object for inspection."""
        import json

        value: object = json.loads(self.json)
        if not isinstance(value, dict):
            raise ValueError("native plan result is not an object")
        return cast(dict[str, object], value)

    @property
    def plan_id(self) -> str:
        """Return the stable plan identifier."""
        value = self.document.get("plan_id")
        if not isinstance(value, str):
            raise ValueError("native plan result has no plan_id")
        return value

    @property
    def operation_count(self) -> int:
        """Return the number of planned operations."""
        value = self.document.get("operations")
        if not isinstance(value, list):
            raise ValueError("native plan result has no operations")
        return len(cast(list[object], value))


@dataclass(frozen=True, slots=True)
class ApplyRequest:
    """Typed plan-application request."""

    root: Path
    plan: PlanResult
    new_project: bool


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Successful transaction result."""

    plan_id: str
    operation_count: int
    state_path: Path


@dataclass(frozen=True, slots=True)
class ReleaseState:
    """Persisted local release-flow state."""

    version: str
    branch: str
    source_commit: str
    catalog_hash: str
    phase: ReleasePhase


def to_jsonable(value: object) -> object:
    """Convert public dataclasses, enums, paths, tuples, and maps to JSON values."""
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, GitOptions):
        return {
            "enabled": value.enabled,
            "initial_branch": value.initial_branch,
            "initial_commit": value.initial_commit,
        }
    if isinstance(value, SnapshotFile):
        return {"hash": value.hash, "ownership": to_jsonable(value.ownership)}
    if isinstance(value, RepositorySnapshot):
        return {
            "exists": value.exists,
            "git": value.git,
            "primary_branch": value.primary_branch,
            "files": to_jsonable(value.files),
        }
    if isinstance(value, VersionCatalog):
        return {
            "id": value.id,
            "hash": value.hash,
            "resolved_at": value.resolved_at,
            "source": value.source,
            "versions": to_jsonable(value.versions),
            "images": to_jsonable(value.images),
        }
    if isinstance(value, RenderedFile):
        return {
            "path": value.path,
            "content": value.content,
            "ownership": to_jsonable(value.ownership),
        }
    if isinstance(value, ReleaseState):
        return {
            "version": value.version,
            "branch": value.branch,
            "source_commit": value.source_commit,
            "catalog_hash": value.catalog_hash,
            "phase": str(value.phase),
        }
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {str(key): to_jsonable(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast(list[object] | tuple[object, ...], value)
        return [to_jsonable(item) for item in sequence]
    return value
