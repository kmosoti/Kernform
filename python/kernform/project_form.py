"""Typed v2 project-form decoding and explicit v1 identity mapping."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from kernform.errors import KernformPolicyError, KernformPreconditionError
from kernform.models import GitOptions, LegacyProfile, Signature

PROJECT_FORM_SCHEMA = "kernform.project-form/v2"
LEGACY_PROJECT_SCHEMA = "kernform/v1"

_ROOT_FIELDS = {
    "schema",
    "generator_version",
    "project",
    "runtime",
    "git",
    "versions",
    "web",
    "containers",
}
_PROJECT_FIELDS = {
    "name",
    "requested_signatures",
    "resolved_signatures",
    "capabilities",
}
_LEGACY_ROOT_FIELDS = {
    "schema",
    "generator_version",
    "project",
    "git",
    "versions",
    "web",
    "containers",
}
_LEGACY_PROJECT_FIELDS = {"name", "profile", "capabilities"}
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9-]*$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class ProjectForm:
    """Closed input needed to compile or regenerate one project form."""

    name: str
    signatures: tuple[Signature, ...]
    default_signature: Signature | None
    capabilities: tuple[str, ...]
    git: GitOptions


def parse_project_form_json(raw: str) -> ProjectForm:
    """Decode exactly one v2 JSON project form."""
    try:
        value: object = json.loads(
            raw,
            object_pairs_hook=_closed_json_object,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as error:
        raise KernformPolicyError(f"project form is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise KernformPolicyError("project form must be a JSON object")
    return parse_project_form(cast(dict[str, object], value))


def parse_project_form(document: dict[str, object]) -> ProjectForm:
    """Validate one closed v2 project form and return its compile-time intent."""
    _require_fields(
        document,
        label="project form",
        required={"schema", "project", "runtime", "git"},
        allowed=_ROOT_FIELDS,
    )
    if document.get("schema") != PROJECT_FORM_SCHEMA:
        raise KernformPolicyError(f"project form schema must be {PROJECT_FORM_SCHEMA}")
    generator_version = document.get("generator_version")
    if generator_version is not None and (
        not isinstance(generator_version, str) or _SEMVER.fullmatch(generator_version) is None
    ):
        raise KernformPolicyError("project form generator_version must be a semantic version")
    project_value = document.get("project")
    if not isinstance(project_value, dict):
        raise KernformPolicyError("project form has no project object")
    project = cast(dict[str, object], project_value)
    _require_fields(
        project,
        label="project form project",
        required={"name", "requested_signatures", "capabilities"},
        allowed=_PROJECT_FIELDS,
    )
    name = project.get("name")
    signatures = _string_tuple(project.get("requested_signatures"), "requested_signatures")
    capabilities = _string_tuple(project.get("capabilities"), "capabilities")
    runtime_value = document.get("runtime")
    git_value = document.get("git")
    if (
        not isinstance(name, str)
        or _NAME.fullmatch(name) is None
        or not isinstance(runtime_value, dict)
    ):
        raise KernformPolicyError("project form identity fields are invalid")
    runtime = cast(dict[str, object], runtime_value)
    _require_fields(
        runtime,
        label="project form runtime",
        required=set(),
        allowed={"default_signature"},
    )
    default_value = runtime.get("default_signature")
    if default_value is not None and not isinstance(default_value, str):
        raise KernformPolicyError("runtime.default_signature must be a signature string")
    try:
        typed_signatures = tuple(Signature(value) for value in signatures)
        default_signature = Signature(default_value) if isinstance(default_value, str) else None
    except ValueError as error:
        raise KernformPolicyError(f"project form contains an unknown signature: {error}") from error
    if not typed_signatures or len(set(typed_signatures)) != len(typed_signatures):
        raise KernformPolicyError("requested_signatures must contain unique values")
    if len(set(capabilities)) != len(capabilities) or any(
        _CAPABILITY.fullmatch(capability) is None for capability in capabilities
    ):
        raise KernformPolicyError("capabilities must contain unique lower-kebab-case values")

    # Import locally so the decoder can validate native signature closure without
    # introducing an import cycle with the generation shell.
    from kernform.generation import resolve_project_signatures

    resolution = resolve_project_signatures(typed_signatures, default_signature)
    declared_resolved_value = project.get("resolved_signatures")
    if declared_resolved_value is not None:
        declared_resolved = _string_tuple(declared_resolved_value, "resolved_signatures")
        try:
            typed_resolved = tuple(Signature(value) for value in declared_resolved)
        except ValueError as error:
            raise KernformPolicyError(
                f"project form contains an unknown resolved signature: {error}"
            ) from error
        if (
            not typed_resolved
            or len(set(typed_resolved)) != len(typed_resolved)
            or set(typed_resolved) != set(resolution.resolved)
        ):
            expected = ", ".join(signature.value for signature in resolution.resolved)
            raise KernformPolicyError(
                f"resolved_signatures do not match native resolution; expected [{expected}]"
            )

    _validate_versions(document.get("versions"))
    _validate_web(document.get("web"))
    _validate_containers(document.get("containers"))
    return ProjectForm(
        name=name,
        signatures=typed_signatures,
        default_signature=default_signature,
        capabilities=capabilities,
        git=_git_options(git_value),
    )


def read_project_form(root: Path, *, allow_legacy: bool = False) -> ProjectForm:
    """Read a managed TOML manifest without mutating or normalizing it."""
    path = root / "kernform.toml"
    if not path.is_file():
        raise KernformPreconditionError(f"project manifest is missing: {path}")
    with path.open("rb") as source:
        document = cast(dict[str, object], tomllib.load(source))
    schema = document.get("schema")
    if schema == PROJECT_FORM_SCHEMA:
        return parse_project_form(document)
    if schema == LEGACY_PROJECT_SCHEMA and allow_legacy:
        return parse_legacy_project_form(document)
    if schema == LEGACY_PROJECT_SCHEMA:
        raise KernformPreconditionError(
            "legacy project form requires an explicit `kernform migrate plan` operation"
        )
    raise KernformPolicyError(f"unsupported project form schema: {schema!r}")


def parse_legacy_project_form(document: dict[str, object]) -> ProjectForm:
    """Map a v1 identity to its deterministic v2 signature target in memory."""
    _require_fields(
        document,
        label="legacy project form",
        required=_LEGACY_ROOT_FIELDS,
        allowed=_LEGACY_ROOT_FIELDS,
    )
    if document.get("schema") != LEGACY_PROJECT_SCHEMA:
        raise KernformPolicyError(f"legacy project schema must be {LEGACY_PROJECT_SCHEMA}")
    generator_version = document.get("generator_version")
    if not isinstance(generator_version, str) or _SEMVER.fullmatch(generator_version) is None:
        raise KernformPolicyError(
            "legacy project form generator_version must be a semantic version"
        )
    project_value = document.get("project")
    if not isinstance(project_value, dict):
        raise KernformPolicyError("legacy project form has no project table")
    project = cast(dict[str, object], project_value)
    _require_fields(
        project,
        label="legacy project form project",
        required=_LEGACY_PROJECT_FIELDS,
        allowed=_LEGACY_PROJECT_FIELDS,
    )
    name = project.get("name")
    profile_value = project.get("profile")
    capabilities = _string_tuple(project.get("capabilities"), "capabilities")
    if (
        not isinstance(name, str)
        or _NAME.fullmatch(name) is None
        or not isinstance(profile_value, str)
        or len(set(capabilities)) != len(capabilities)
        or any(_CAPABILITY.fullmatch(capability) is None for capability in capabilities)
    ):
        raise KernformPolicyError("legacy project identity fields are invalid")
    try:
        profile = LegacyProfile(profile_value)
    except ValueError as error:
        raise KernformPolicyError(f"unknown legacy profile: {profile_value}") from error
    signature = {
        LegacyProfile.LIBRARY: Signature.SDK,
        LegacyProfile.CLI: Signature.CLI,
        LegacyProfile.API: (
            Signature.INTERACTIVE_WEB if "web-server" in capabilities else Signature.API
        ),
    }[profile]
    _validate_legacy_versions(document.get("versions"))
    _validate_web(document.get("web"))
    _validate_containers(document.get("containers"))
    return ProjectForm(
        name=name,
        signatures=(signature,),
        default_signature=None if signature is Signature.SDK else signature,
        capabilities=tuple(capability for capability in capabilities if capability != "web-server"),
        git=_git_options(document.get("git")),
    )


def _git_options(value: object) -> GitOptions:
    if not isinstance(value, dict):
        raise KernformPolicyError("project form has no git object")
    git = cast(dict[str, object], value)
    _require_fields(
        git,
        label="project form git",
        required={"enabled", "initial_branch", "initial_commit", "create_remote"},
        allowed={"enabled", "initial_branch", "initial_commit", "create_remote"},
    )
    enabled = git.get("enabled")
    branch = git.get("initial_branch")
    initial_commit = git.get("initial_commit", False)
    create_remote = git.get("create_remote")
    if (
        not isinstance(enabled, bool)
        or not isinstance(branch, str)
        or not _valid_initial_branch(branch)
        or initial_commit is not False
        or create_remote is not False
    ):
        raise KernformPolicyError("project form git fields are invalid")
    return GitOptions(enabled=enabled, initial_branch=branch, initial_commit=initial_commit)


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise KernformPolicyError(f"project form {label} must be an array")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise KernformPolicyError(f"project form {label} must contain only strings")
    return tuple(cast(list[str], items))


def _require_fields(
    value: dict[str, object],
    *,
    label: str,
    required: set[str],
    allowed: set[str],
) -> None:
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - allowed)
    if missing:
        raise KernformPolicyError(f"{label} is missing required fields: {', '.join(missing)}")
    if unknown:
        raise KernformPolicyError(f"{label} contains unknown fields: {', '.join(unknown)}")


def _closed_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise KernformPolicyError(f"project form JSON contains duplicate field: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise KernformPolicyError(f"project form JSON contains non-finite value: {value}")


def _valid_initial_branch(value: str) -> bool:
    if (
        not value
        or len(value.encode("utf-8")) > 255
        or value == "HEAD"
        or value == "@"
        or value.startswith("-")
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
        or ".." in value
        or "@{" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(character in " ~^:?*[\\" for character in value)
    ):
        return False
    return all(
        component
        and not component.startswith(".")
        and not component.endswith(".")
        and not component.endswith(".lock")
        for component in value.split("/")
    )


def _validate_versions(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise KernformPolicyError("project form versions must be an object")
    versions = cast(dict[str, object], value)
    _require_fields(
        versions,
        label="project form versions",
        required={"policy", "allow_prerelease", "catalog_id", "catalog_hash"},
        allowed={"policy", "allow_prerelease", "catalog_id", "catalog_hash"},
    )
    catalog_id = versions.get("catalog_id")
    catalog_hash = versions.get("catalog_hash")
    if (
        versions.get("policy") != "newest-stable-exact"
        or versions.get("allow_prerelease") is not False
        or not isinstance(catalog_id, str)
        or not catalog_id
        or not isinstance(catalog_hash, str)
        or _SHA256.fullmatch(catalog_hash) is None
    ):
        raise KernformPolicyError("project form versions fields are invalid")


def _validate_legacy_versions(value: object) -> None:
    if not isinstance(value, dict):
        raise KernformPolicyError("legacy project form versions must be an object")
    versions = cast(dict[str, object], value)
    _require_fields(
        versions,
        label="legacy project form versions",
        required={"policy", "allow_prerelease", "offline_catalog"},
        allowed={"policy", "allow_prerelease", "offline_catalog"},
    )
    offline_catalog = versions.get("offline_catalog")
    if (
        versions.get("policy") != "newest-stable-exact"
        or versions.get("allow_prerelease") is not False
        or not isinstance(offline_catalog, str)
        or not offline_catalog
        or "\x00" in offline_catalog
    ):
        raise KernformPolicyError("legacy project form versions fields are invalid")


def _validate_web(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise KernformPolicyError("project form web must be an object")
    web = cast(dict[str, object], value)
    _require_fields(
        web,
        label="project form web",
        required={"javascript"},
        allowed={"javascript"},
    )
    if web.get("javascript") != "none":
        raise KernformPolicyError("project form web.javascript must be 'none'")


def _validate_containers(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise KernformPolicyError("project form containers must be an object")
    containers = cast(dict[str, object], value)
    _require_fields(
        containers,
        label="project form containers",
        required={"engine", "rootless"},
        allowed={"engine", "rootless"},
    )
    if containers.get("engine") != "podman" or containers.get("rootless") is not True:
        raise KernformPolicyError("project form containers must select rootless Podman")
