from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator

import kernform
from kernform.cli import build_parser, dispatch, main
from kernform.errors import KernformPolicyError, KernformPreconditionError
from kernform.migration import (
    apply_project_migration,
    parse_migration_plan,
    plan_project_migration,
)
from kernform.project_form import (
    parse_legacy_project_form,
    parse_project_form,
    parse_project_form_json,
)

ROOT = Path(__file__).resolve().parents[2]


def _form(name: str, *signatures: str, default: str | None = None) -> dict[str, object]:
    return {
        "schema": "kernform.project-form/v2",
        "project": {
            "name": name,
            "requested_signatures": list(signatures),
            "capabilities": [],
        },
        "runtime": {} if default is None else {"default_signature": default},
        "git": {
            "enabled": False,
            "initial_branch": "main",
            "initial_commit": False,
            "create_remote": False,
        },
    }


def _legacy_form() -> dict[str, object]:
    return {
        "schema": "kernform/v1",
        "generator_version": "0.1.0",
        "project": {
            "name": "legacy-project",
            "profile": "cli",
            "capabilities": ["python-package", "cli"],
        },
        "git": {
            "enabled": False,
            "initial_branch": "main",
            "initial_commit": False,
            "create_remote": False,
        },
        "versions": {
            "policy": "newest-stable-exact",
            "allow_prerelease": False,
            "offline_catalog": "fixtures/catalogs/stable-v1.json",
        },
        "web": {"javascript": "none"},
        "containers": {"engine": "podman", "rootless": True},
    }


def _migration_document() -> dict[str, object]:
    plan = kernform.plan_project(
        name="example",
        git=kernform.GitOptions(enabled=False),
    ).document
    payload = {
        "source_schema": "kernform/v1",
        "target_schema": "kernform.project-form/v2",
        "source_manifest_hash": "1" * 64,
        "project_name": "example",
        "plan_id": plan["plan_id"],
    }
    migration_id = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema": "kernform.migration-plan/v1",
        "migration_id": migration_id,
        "source_schema": "kernform/v1",
        "target_schema": "kernform.project-form/v2",
        "source_manifest_hash": "1" * 64,
        "project_name": "example",
        "plan": plan,
    }


def test_project_form_decoder_rejects_unknown_fields() -> None:
    forms: list[dict[str, object]] = []
    for section in (None, "project", "runtime", "git"):
        document = json.loads(json.dumps(_form("closed-form", "sdk")))
        target = document if section is None else cast(dict[str, object], document[section])
        target["unexpected"] = True
        forms.append(document)

    for document in forms:
        with pytest.raises(KernformPolicyError, match="unknown fields"):
            parse_project_form(document)


def test_project_form_json_decoder_rejects_duplicate_and_non_finite_values() -> None:
    duplicate = json.dumps(_form("closed-form", "sdk")).replace(
        '"schema": "kernform.project-form/v2"',
        '"schema": "kernform.project-form/v2", "schema": "kernform.project-form/v2"',
        1,
    )
    with pytest.raises(KernformPolicyError, match="duplicate field"):
        parse_project_form_json(duplicate)

    non_finite = json.dumps(_form("closed-form", "sdk")).replace(
        '"capabilities": []',
        '"capabilities": [NaN]',
        1,
    )
    with pytest.raises(KernformPolicyError, match="non-finite"):
        parse_project_form_json(non_finite)


def test_project_form_decoder_enforces_closed_values_and_native_resolution() -> None:
    remote = _form("closed-form", "sdk")
    cast(dict[str, object], remote["git"])["create_remote"] = True
    with pytest.raises(KernformPolicyError, match="git fields"):
        parse_project_form(remote)

    duplicate_capability = _form("closed-form", "sdk")
    cast(dict[str, object], duplicate_capability["project"])["capabilities"] = [
        "testing",
        "testing",
    ]
    with pytest.raises(KernformPolicyError, match="unique lower-kebab-case"):
        parse_project_form(duplicate_capability)

    stale_resolution = _form("closed-form", "cli", "daemon", default="daemon")
    cast(dict[str, object], stale_resolution["project"])["resolved_signatures"] = [
        "cli",
        "daemon",
    ]
    with pytest.raises(KernformPolicyError, match="native resolution"):
        parse_project_form(stale_resolution)


@pytest.mark.parametrize(
    "branch",
    ["HEAD", "@", "-topic", "topic..child", "topic/.child", "topic.lock"],
)
def test_project_form_decoder_rejects_unsafe_initial_branch(branch: str) -> None:
    document = _form("closed-form", "sdk")
    cast(dict[str, object], document["git"])["initial_branch"] = branch
    with pytest.raises(KernformPolicyError, match="git fields"):
        parse_project_form(document)


def test_project_form_decoder_rejects_initial_commit() -> None:
    document = _form("closed-form", "sdk")
    cast(dict[str, object], document["git"])["initial_commit"] = True
    with pytest.raises(KernformPolicyError, match="git fields"):
        parse_project_form(document)


@pytest.mark.parametrize("section", [None, "project", "git", "versions", "web", "containers"])
def test_legacy_project_form_rejects_unknown_fields(section: str | None) -> None:
    document = _legacy_form()
    target = document if section is None else cast(dict[str, object], document[section])
    target["unexpected"] = True
    with pytest.raises(KernformPolicyError, match="unknown fields"):
        parse_legacy_project_form(document)


def test_project_form_schemas_reject_disallowed_git_values() -> None:
    current = json.loads((ROOT / "schemas/kernform.schema.json").read_text())
    legacy = json.loads((ROOT / "schemas/legacy/kernform-v1.schema.json").read_text())
    for schema, document in ((current, _form("example", "sdk")), (legacy, _legacy_form())):
        unsafe = json.loads(json.dumps(document))
        cast(dict[str, object], unsafe["git"])["initial_branch"] = "topic/.hidden"
        assert not Draft202012Validator(schema).is_valid(unsafe)  # pyright: ignore[reportUnknownMemberType]
        committing = json.loads(json.dumps(document))
        cast(dict[str, object], committing["git"])["initial_commit"] = True
        assert not Draft202012Validator(schema).is_valid(committing)  # pyright: ignore[reportUnknownMemberType]


def test_agent_compile_and_init_accept_project_form_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    form_path = tmp_path / "form.json"
    form_path.write_text(
        json.dumps(_form("combined", "cli", "daemon", default="daemon")),
        encoding="utf-8",
    )
    assert main(["--agent", "compile", "--form", str(form_path)]) == 0
    compiled = json.loads(capsys.readouterr().out)
    assert compiled["schema"] == "kernform.command/v2"
    assert compiled["result"]["schema"] == "kernform.plan/v2"
    assert compiled["result"]["intent"]["default_signature"] == "daemon"

    destination = tmp_path / "combined"
    assert (
        main(
            [
                "--agent",
                "init",
                "--form",
                str(form_path),
                "--destination",
                str(destination),
            ]
        )
        == 0
    )
    initialized = json.loads(capsys.readouterr().out)
    assert initialized["status"] == "success"
    state = json.loads((destination / ".kernform/state.json").read_text(encoding="utf-8"))
    assert state["schema"] == "kernform.state/v2"
    assert state["requested_signatures"] == ["cli", "daemon"]
    assert state["default_signature"] == "daemon"
    manifest = (destination / "kernform.toml").read_text(encoding="utf-8")
    assert 'requested_signatures = ["cli", "daemon"]' in manifest
    assert (destination / "python/combined/daemon.py").is_file()
    assert (destination / "python/combined/cli.py").is_file()
    checked = dispatch(build_parser().parse_args(["check", str(destination)]))
    assert checked.status == "success"
    assert cast(dict[str, object], checked.result)["conformant"] is True
    adopted = dispatch(
        build_parser().parse_args(["adopt", str(destination), "--form", str(form_path), "--yes"])
    )
    assert adopted.status == "success"
    assert cast(dict[str, object], adopted.result)["operation_count"] == 0


def test_v1_check_is_read_only_and_migration_is_explicit(tmp_path: Path) -> None:
    project = tmp_path / "legacy-project"
    kernform.initialize_project(
        kernform.InitRequest(
            name="legacy-project",
            destination=project,
            signatures=(kernform.Signature.CLI,),
            git=kernform.GitOptions(enabled=False),
        )
    )
    legacy_manifest = """schema = "kernform/v1"
generator_version = "0.1.0"

[project]
name = "legacy-project"
profile = "cli"
capabilities = [
  "python-package", "rust-core", "pyo3-bindings", "testing", "locks-base", "ci",
  "release", "podman", "nushell-human", "nushell-agent", "cli",
]

[git]
enabled = false
initial_branch = "main"
initial_commit = false
create_remote = false

[versions]
policy = "newest-stable-exact"
allow_prerelease = false
offline_catalog = "fixtures/catalogs/stable-v1.json"

[web]
javascript = "none"

[containers]
engine = "podman"
rootless = true
"""
    manifest_path = project / "kernform.toml"
    manifest_path.write_text(legacy_manifest, encoding="utf-8")
    digest = hashlib.sha256(legacy_manifest.encode()).hexdigest()
    state_path = project / ".kernform/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["schema"] = "kernform.state/v1"
    state["generator_version"] = "0.1.0"
    state["manifest_hash"] = digest
    state.pop("requested_signatures")
    state.pop("resolved_signatures")
    state.pop("default_signature")
    for entry in state["files"]:
        if entry["path"] == "kernform.toml":
            entry["hash"] = digest
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

    before = manifest_path.read_bytes()
    envelope = dispatch(build_parser().parse_args(["check", str(project)]))
    assert envelope.status == "success"
    result = cast(dict[str, object], envelope.result)
    assert result["migration_required"] is True
    assert result["mapped_signatures"] == ["cli"]
    assert manifest_path.read_bytes() == before

    migration = plan_project_migration(project)
    schema = json.loads((ROOT / "schemas/migration-plan.schema.json").read_text())
    Draft202012Validator(schema).validate(  # pyright: ignore[reportUnknownMemberType]
        migration.document
    )
    manifest_path.write_text(f"{legacy_manifest}\n# changed after planning\n", encoding="utf-8")
    with pytest.raises(KernformPreconditionError, match="changed after migration planning"):
        apply_project_migration(project, migration)
    manifest_path.write_text(legacy_manifest, encoding="utf-8")
    applied = apply_project_migration(project, migration)
    assert applied.operation_count > 0
    assert 'schema = "kernform.project-form/v2"' in manifest_path.read_text(encoding="utf-8")
    migrated_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert migrated_state["schema"] == "kernform.state/v2"
    assert migrated_state["requested_signatures"] == ["cli"]


def test_migration_plan_accepts_direct_document_and_command_envelope() -> None:
    document = _migration_document()
    assert parse_migration_plan(json.dumps(document)).project_name == "example"
    envelope: dict[str, object] = {
        "schema": "kernform.command/v2",
        "command": "migrate plan",
        "status": "success",
        "exit_code": 0,
        "result": document,
        "diagnostics": [],
        "artifacts": [],
    }
    assert parse_migration_plan(json.dumps(envelope)).migration_id == document["migration_id"]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ('{"schema":"kernform.migration-plan/v1","schema":"duplicate"}', "duplicate"),
        ('{"schema":"kernform.migration-plan/v1","value":NaN}', "non-finite"),
        ("[]", "JSON object"),
    ],
)
def test_migration_plan_rejects_non_closed_json(raw: str, message: str) -> None:
    with pytest.raises(KernformPolicyError, match=message):
        parse_migration_plan(raw)


def test_migration_plan_rejects_unknown_envelope_and_plan_fields() -> None:
    document = _migration_document()
    document["unexpected"] = True
    with pytest.raises(KernformPolicyError, match="unknown fields"):
        parse_migration_plan(json.dumps(document))

    envelope: dict[str, object] = {
        "schema": "kernform.command/v2",
        "command": "migrate plan",
        "status": "success",
        "exit_code": 0,
        "result": _migration_document(),
        "diagnostics": [],
        "artifacts": [],
        "unexpected": True,
    }
    with pytest.raises(KernformPolicyError, match="unknown fields"):
        parse_migration_plan(json.dumps(envelope))


def test_migration_plan_rejects_embedded_plan_tampering() -> None:
    document = _migration_document()
    plan = cast(dict[str, object], document["plan"])
    operations = cast(list[dict[str, object]], plan["operations"])
    write = next(operation for operation in operations if operation["kind"] == "write_file")
    write["content"] = "tampered\n"
    with pytest.raises(KernformPolicyError, match="invalid plan"):
        parse_migration_plan(json.dumps(document))


def test_migration_plan_rejects_project_name_mismatch() -> None:
    document = _migration_document()
    document["project_name"] = "another-project"
    payload = {
        "source_schema": document["source_schema"],
        "target_schema": document["target_schema"],
        "source_manifest_hash": document["source_manifest_hash"],
        "project_name": document["project_name"],
        "plan_id": cast(dict[str, object], document["plan"])["plan_id"],
    }
    document["migration_id"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(KernformPolicyError, match="target does not match"):
        parse_migration_plan(json.dumps(document))
