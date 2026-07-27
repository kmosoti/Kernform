"""Explicit, replayable v1-to-v2 project migration plans."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from kernform import _native
from kernform.errors import KernformPolicyError, KernformPreconditionError
from kernform.generation import apply_adoption, plan_adoption
from kernform.models import ApplyResult, PlanResult, to_jsonable
from kernform.project_form import LEGACY_PROJECT_SCHEMA, ProjectForm, read_project_form

MIGRATION_PLAN_SCHEMA = "kernform.migration-plan/v1"
_COMMAND_SCHEMA = "kernform.command/v2"
_PROJECT_FORM_SCHEMA = "kernform.project-form/v2"
_MIGRATION_FIELDS = {
    "schema",
    "migration_id",
    "source_schema",
    "target_schema",
    "source_manifest_hash",
    "project_name",
    "plan",
}
_COMMAND_FIELDS = {
    "schema",
    "command",
    "status",
    "exit_code",
    "result",
    "diagnostics",
    "artifacts",
}
_PROJECT_NAME = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_DIAGNOSTIC_ID = re.compile(r"^KF-[A-Z]+-[0-9]{3}$")


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """Immutable migration wrapper around an ordinary v2 apply plan."""

    migration_id: str
    source_schema: str
    target_schema: str
    source_manifest_hash: str
    project_name: str
    plan: PlanResult

    @property
    def document(self) -> dict[str, object]:
        """Return the exact machine-readable migration document."""
        return {
            "schema": MIGRATION_PLAN_SCHEMA,
            "migration_id": self.migration_id,
            "source_schema": self.source_schema,
            "target_schema": self.target_schema,
            "source_manifest_hash": self.source_manifest_hash,
            "project_name": self.project_name,
            "plan": self.plan.document,
        }


def plan_project_migration(root: Path, target: ProjectForm | None = None) -> MigrationPlan:
    """Compile a read-only v1-to-v2 migration plan against live repository state."""
    canonical = root.resolve(strict=True)
    source_path = canonical / "kernform.toml"
    if not source_path.is_file():
        raise KernformPreconditionError(f"project manifest is missing: {source_path}")
    source = source_path.read_bytes()
    legacy_target = read_project_form(canonical, allow_legacy=True)
    chosen = target or legacy_target
    if chosen.name != legacy_target.name:
        raise KernformPolicyError("migration cannot rename the existing project")
    plan = plan_adoption(
        canonical,
        name=chosen.name,
        signatures=chosen.signatures,
        default_signature=chosen.default_signature,
        capabilities=chosen.capabilities,
        git=chosen.git,
    )
    source_hash = hashlib.sha256(source).hexdigest()
    payload = {
        "source_schema": LEGACY_PROJECT_SCHEMA,
        "target_schema": _PROJECT_FORM_SCHEMA,
        "source_manifest_hash": source_hash,
        "project_name": chosen.name,
        "plan_id": plan.plan_id,
    }
    migration_id = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
    return MigrationPlan(
        migration_id=migration_id,
        source_schema=LEGACY_PROJECT_SCHEMA,
        target_schema=_PROJECT_FORM_SCHEMA,
        source_manifest_hash=source_hash,
        project_name=chosen.name,
        plan=plan,
    )


def parse_migration_plan(raw: str) -> MigrationPlan:
    """Decode and validate a persisted migration plan without applying it."""
    try:
        value: object = json.loads(
            raw,
            object_pairs_hook=_closed_json_object,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as error:
        raise KernformPolicyError(f"migration plan is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise KernformPolicyError("migration plan must be a JSON object")
    document = cast(dict[str, object], value)
    if document.get("schema") == _COMMAND_SCHEMA:
        _require_fields(document, _COMMAND_FIELDS, "migration command envelope")
        result = document.get("result")
        if (
            document.get("command") != "migrate plan"
            or document.get("status") != "success"
            or document.get("exit_code") != 0
            or not isinstance(result, dict)
            or not isinstance(document.get("diagnostics"), list)
            or not isinstance(document.get("artifacts"), list)
        ):
            raise KernformPolicyError("migration command envelope is invalid")
        _validate_diagnostics(document.get("diagnostics"))
        _validate_artifacts(document.get("artifacts"))
        document = cast(dict[str, object], result)
    _require_fields(document, _MIGRATION_FIELDS, "migration plan")
    schema = document.get("schema")
    migration_id = document.get("migration_id")
    source_schema = document.get("source_schema")
    target_schema = document.get("target_schema")
    source_hash = document.get("source_manifest_hash")
    project_name = document.get("project_name")
    plan = document.get("plan")
    if (
        schema != MIGRATION_PLAN_SCHEMA
        or source_schema != LEGACY_PROJECT_SCHEMA
        or target_schema != _PROJECT_FORM_SCHEMA
        or not isinstance(migration_id, str)
        or _SHA256.fullmatch(migration_id) is None
        or not isinstance(source_hash, str)
        or _SHA256.fullmatch(source_hash) is None
        or not isinstance(project_name, str)
        or _PROJECT_NAME.fullmatch(project_name) is None
        or not isinstance(plan, dict)
    ):
        raise KernformPolicyError("migration plan has invalid identity fields")
    typed_migration_id = migration_id
    typed_source_schema = cast(str, source_schema)
    typed_target_schema = cast(str, target_schema)
    typed_source_hash = source_hash
    typed_project_name = project_name
    try:
        validated_plan = _native.validate_plan_json(_canonical_json(cast(dict[str, object], plan)))
    except (KernformPolicyError, ValueError) as error:
        raise KernformPolicyError(f"migration plan contains an invalid plan: {error}") from error
    plan_result = PlanResult(validated_plan)
    plan_document = plan_result.document
    plan_intent = plan_document.get("intent")
    typed_plan_intent = (
        cast(dict[str, object], plan_intent) if isinstance(plan_intent, dict) else None
    )
    if (
        plan_document.get("schema") != "kernform.plan/v2"
        or typed_plan_intent is None
        or typed_plan_intent.get("name") != typed_project_name
    ):
        raise KernformPolicyError("migration plan target does not match its embedded plan")
    expected_payload = {
        "source_schema": typed_source_schema,
        "target_schema": typed_target_schema,
        "source_manifest_hash": typed_source_hash,
        "project_name": typed_project_name,
        "plan_id": plan_result.plan_id,
    }
    expected_id = hashlib.sha256(_canonical_json(expected_payload).encode()).hexdigest()
    if typed_migration_id != expected_id:
        raise KernformPolicyError("migration plan identity does not match its content")
    return MigrationPlan(
        migration_id=typed_migration_id,
        source_schema=typed_source_schema,
        target_schema=typed_target_schema,
        source_manifest_hash=typed_source_hash,
        project_name=typed_project_name,
        plan=plan_result,
    )


def apply_project_migration(root: Path, migration: MigrationPlan) -> ApplyResult:
    """Apply a confirmed migration only if its source precondition still holds."""
    canonical = root.resolve(strict=True)
    source_path = canonical / "kernform.toml"
    if not source_path.is_file():
        raise KernformPreconditionError(f"project manifest is missing: {source_path}")
    actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if actual_hash != migration.source_manifest_hash:
        raise KernformPreconditionError("legacy project form changed after migration planning")
    if canonical.name.replace("_", "-").lower() != migration.project_name:
        manifest_identity = read_project_form(canonical, allow_legacy=True)
        if manifest_identity.name != migration.project_name:
            raise KernformPreconditionError("migration plan targets a different project")
    return apply_adoption(canonical, migration.plan)


def _canonical_json(value: object) -> str:
    return json.dumps(to_jsonable(value), sort_keys=True, separators=(",", ":"))


def _closed_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise KernformPolicyError(f"migration plan JSON contains duplicate field: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise KernformPolicyError(f"migration plan JSON contains non-finite value: {value}")


def _require_fields(document: dict[str, object], expected: set[str], label: str) -> None:
    missing = sorted(expected - document.keys())
    unknown = sorted(document.keys() - expected)
    if missing:
        raise KernformPolicyError(f"{label} is missing required fields: {', '.join(missing)}")
    if unknown:
        raise KernformPolicyError(f"{label} contains unknown fields: {', '.join(unknown)}")


def _validate_diagnostics(value: object) -> None:
    assert isinstance(value, list)
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            raise KernformPolicyError("migration command envelope diagnostics are invalid")
        diagnostic = cast(dict[str, object], item)
        _require_fields(
            diagnostic,
            {"id", "severity", "message", "context"},
            "migration command diagnostic",
        )
        if (
            not isinstance(diagnostic.get("id"), str)
            or _DIAGNOSTIC_ID.fullmatch(cast(str, diagnostic.get("id"))) is None
            or diagnostic.get("severity") not in {"info", "warning", "error"}
            or not isinstance(diagnostic.get("message"), str)
            or not cast(str, diagnostic.get("message"))
            or not isinstance(diagnostic.get("context"), dict)
        ):
            raise KernformPolicyError("migration command envelope diagnostics are invalid")


def _validate_artifacts(value: object) -> None:
    assert isinstance(value, list)
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            raise KernformPolicyError("migration command envelope artifacts are invalid")
        artifact = cast(dict[str, object], item)
        _require_fields(
            artifact,
            {"kind", "path", "hash"},
            "migration command artifact",
        )
        digest = artifact.get("hash")
        if (
            not isinstance(artifact.get("kind"), str)
            or not cast(str, artifact.get("kind"))
            or not isinstance(artifact.get("path"), str)
            or not cast(str, artifact.get("path"))
            or (
                digest is not None
                and (not isinstance(digest, str) or _SHA256.fullmatch(digest) is None)
            )
        ):
            raise KernformPolicyError("migration command envelope artifacts are invalid")
