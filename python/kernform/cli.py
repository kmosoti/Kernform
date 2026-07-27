"""Stable Kernform command-line grammar and dispatch."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn, cast

from kernform.api import (
    apply_plan,
    git_initial_commit,
    inspect_repository,
    release_finalize,
    release_inspect,
    release_start,
    release_verify,
    version,
)
from kernform.catalog import load_builtin_catalog
from kernform.container import container_operation, development_operation
from kernform.errors import (
    KernformNativeError,
    KernformPolicyError,
    KernformPreconditionError,
    KernformProcessError,
)
from kernform.generation import apply_adoption, initialize_project, plan_adoption, plan_project
from kernform.migration import (
    apply_project_migration,
    parse_migration_plan,
    plan_project_migration,
)
from kernform.models import (
    ApplyRequest,
    GitOptions,
    InitRequest,
    PlanResult,
    ReleasePhase,
    Signature,
    to_jsonable,
)
from kernform.output import (
    Artifact,
    CommandEnvelope,
    Diagnostic,
    OutputFormat,
    failure,
    render,
    success,
)
from kernform.project_form import (
    LEGACY_PROJECT_SCHEMA,
    PROJECT_FORM_SCHEMA,
    ProjectForm,
    parse_project_form_json,
    read_project_form,
)
from kernform.release_artifacts import build_release_bundle, export_oci_image
from kernform.scaffold import scaffold_module
from kernform.shell import shell_operation
from kernform.testing import run_tier, tier_plan
from kernform.versioning import inspect_version_state, plan_version_update


class CliUsageError(ValueError):
    """Invalid public command grammar."""


class Parser(argparse.ArgumentParser):
    """Parser that returns usage failures to the stable envelope boundary."""

    def error(self, message: str) -> NoReturn:
        raise CliUsageError(message)


def build_parser() -> Parser:
    """Build the stable 0.2.0 command grammar."""
    parser = Parser(prog="kernform")
    parser.add_argument("--version", action="store_true", help="show the Kernform version")
    parser.add_argument("--agent", action="store_true", help="use noninteractive agent policy")
    parser.add_argument("--format", choices=[item.value for item in OutputFormat])
    commands = parser.add_subparsers(dest="command")

    compile_command = commands.add_parser("compile", help="compile project-form JSON")
    compile_command.add_argument("--form", required=True)

    init = commands.add_parser("init", help="initialize a new project")
    init.add_argument("name", nargs="?")
    init.add_argument("--destination", type=Path)
    init.add_argument("--form")
    init.add_argument("--signature", choices=[item.value for item in Signature], action="append")
    init.add_argument("--default-signature", choices=[item.value for item in Signature])
    init.add_argument("--with", dest="capabilities", action="append", default=[])
    init.add_argument("--no-git", action="store_true")
    init.add_argument("--initial-commit", action="store_true")
    init.add_argument("--plan-file", type=Path)

    adopt = commands.add_parser("adopt", help="adopt an existing project")
    adopt.add_argument("path", type=Path, nargs="?", default=Path.cwd())
    adopt.add_argument("--plan-file", type=Path)
    adopt.add_argument("--form")
    adopt.add_argument("--name")
    adopt.add_argument("--signature", choices=[item.value for item in Signature], action="append")
    adopt.add_argument("--default-signature", choices=[item.value for item in Signature])
    adopt.add_argument("--with", dest="capabilities", action="append", default=[])
    adopt.add_argument("--no-git", action="store_true")
    adopt.add_argument("--yes", action="store_true")

    migrate = commands.add_parser("migrate", help="plan or apply an explicit v1 migration")
    migrate_commands = migrate.add_subparsers(dest="migrate_command", required=True)
    migrate_plan = migrate_commands.add_parser("plan")
    migrate_plan.add_argument("path", type=Path)
    migrate_plan.add_argument("--form")
    migrate_apply = migrate_commands.add_parser("apply")
    migrate_apply.add_argument("path", type=Path)
    migrate_apply.add_argument("--plan-file", type=Path, required=True)
    migrate_apply.add_argument("--yes", action="store_true")

    scaffold = commands.add_parser("scaffold", help="add a declared scaffold")
    scaffold.add_argument("kind")
    scaffold.add_argument("name")
    scaffold.add_argument("--path", type=Path, default=Path.cwd())

    inspect = commands.add_parser("inspect", help="inspect repository state")
    inspect.add_argument("path", type=Path, nargs="?", default=Path.cwd())

    check = commands.add_parser("check", help="check managed state and conformance")
    check.add_argument("path", type=Path, nargs="?", default=Path.cwd())

    commands.add_parser("doctor", help="inspect host dependencies")

    test = commands.add_parser("test", help="run a maintained test tier")
    test.add_argument("tier", choices=["fast", "full", "deep"])
    test.add_argument("--path", type=Path, default=Path.cwd())
    test.add_argument("--plan", action="store_true")

    versions = commands.add_parser("versions", help="inspect or update exact versions")
    version_commands = versions.add_subparsers(dest="versions_command", required=True)
    for action in ("inspect", "check", "plan"):
        version_action = version_commands.add_parser(action)
        version_action.add_argument("--path", type=Path, default=Path.cwd())
    update = version_commands.add_parser("update")
    update.add_argument("--accept", action="store_true")
    update.add_argument("--path", type=Path, default=Path.cwd())

    container = commands.add_parser("container", help="manage rootless Podman resources")
    container.add_argument("action", choices=["build", "run", "inspect", "test"])
    container.add_argument("--path", type=Path, default=Path.cwd())

    dev = commands.add_parser("dev", help="manage isolated development environments")
    dev.add_argument("action", choices=["up", "down", "reset", "logs"])
    dev.add_argument("--path", type=Path, default=Path.cwd())

    shell = commands.add_parser("shell", help="launch a Nushell mode")
    shell.add_argument("mode", choices=["human", "agent"])
    shell.add_argument("--path", type=Path, default=Path.cwd())

    release = commands.add_parser("release", help="manage local release state")
    release.add_argument("action", choices=["start", "inspect", "verify", "build", "finalize"])
    release.add_argument("version", nargs="?")
    release.add_argument("--yes", action="store_true")
    release.add_argument("--path", type=Path, default=Path.cwd())
    release.add_argument("--metadata-matches", action="store_true")
    release.add_argument("--synchronized", action="store_true")
    release.add_argument("--verification-complete", action="store_true")
    return parser


def dispatch(args: argparse.Namespace) -> CommandEnvelope:
    """Dispatch parsed arguments through shared public operations."""
    command = cast(str | None, args.command)
    if args.version and command is None:
        return success("version", version())
    if command is None:
        raise CliUsageError("a command is required")
    if command == "compile":
        form = _read_form(cast(str, args.form))
        return success(
            "compile",
            plan_project(
                name=form.name,
                signatures=form.signatures,
                default_signature=form.default_signature,
                capabilities=form.capabilities,
                git=form.git,
            ).document,
        )
    if command == "migrate":
        return _migrate(args)
    if command == "inspect":
        root = cast(Path, args.path)
        return success("inspect", to_jsonable(inspect_repository(root)))
    if command == "check":
        return _check(cast(Path, args.path))
    if command == "doctor":
        return _doctor()
    if command == "versions":
        return _versions(args)
    if command in {"init", "adopt"}:
        return _apply_command(args, command)
    if command == "release":
        return _release(args)
    if command == "scaffold":
        applied = scaffold_module(cast(Path, args.path), cast(str, args.kind), cast(str, args.name))
        return success(
            "scaffold",
            {
                "plan_id": applied.plan_id,
                "operation_count": applied.operation_count,
                "state_path": str(applied.state_path),
            },
            artifacts=(Artifact("managed-state", str(applied.state_path)),),
        )
    if command == "container":
        return success(
            f"container {cast(str, args.action)}",
            container_operation(cast(Path, args.path), cast(str, args.action)),
        )
    if command == "dev":
        return success(
            f"dev {cast(str, args.action)}",
            development_operation(cast(Path, args.path), cast(str, args.action)),
        )
    if command == "shell":
        mode = cast(str, args.mode)
        return success(
            f"shell {mode}",
            shell_operation(
                cast(Path, args.path),
                mode,
                interactive=(
                    mode == "human"
                    and not cast(bool, args.agent)
                    and sys.stdin.isatty()
                    and sys.stdout.isatty()
                ),
            ),
        )
    if command == "test":
        return _test(args)
    return failure(
        command,
        5,
        Diagnostic(
            "KF-BOUNDARY-001",
            "error",
            f"{command} handler is not enabled by the current project capabilities",
            {"command": command},
        ),
        refused=True,
    )


def _test(args: argparse.Namespace) -> CommandEnvelope:
    tier = cast(str, args.tier)
    if cast(bool, args.plan):
        return success(f"test {tier}", tier_plan(tier))
    report = run_tier(cast(Path, args.path), tier)
    if report["status"] == "passed":
        return success(f"test {tier}", report)
    return CommandEnvelope(
        command=f"test {tier}",
        status="failure",
        exit_code=2,
        result=report,
        diagnostics=(
            Diagnostic(
                "KF-TEST-001",
                "error",
                f"{tier} test tier failed",
                {"tier": tier},
            ),
        ),
    )


def _apply_command(args: argparse.Namespace, command: str) -> CommandEnvelope:
    plan_path = cast(Path | None, args.plan_file)
    if command == "adopt" and not cast(bool, args.yes):
        return failure(
            command,
            5,
            Diagnostic(
                "KF-STATE-001",
                "error",
                "adoption requires explicit --yes confirmation",
            ),
            refused=True,
        )
    form = (
        None
        if plan_path is not None
        else _form_from_arguments(
            args,
            fallback_name=(
                cast(Path, args.path).name.replace("_", "-").lower() if command == "adopt" else None
            ),
        )
    )
    if command == "adopt":
        root = cast(Path, args.path)
    else:
        destination = cast(Path | None, args.destination)
        direct_name = cast(str | None, args.name)
        if destination is None and direct_name is None and form is None:
            raise CliUsageError("init with --plan-file requires NAME or --destination")
        root = destination or Path(direct_name or cast(ProjectForm, form).name)
    if plan_path is not None:
        plan = PlanResult(plan_path.read_text(encoding="utf-8"))
        applied = apply_plan(ApplyRequest(root, plan, new_project=command == "init"))
    elif command == "init":
        typed_form = cast(ProjectForm, form)
        applied = initialize_project(
            InitRequest(
                name=typed_form.name,
                destination=root,
                signatures=typed_form.signatures,
                default_signature=typed_form.default_signature,
                capabilities=typed_form.capabilities,
                git=typed_form.git,
            )
        )
        if cast(bool, args.initial_commit):
            git_initial_commit(root)
    else:
        typed_form = cast(ProjectForm, form)
        plan = plan_adoption(
            root,
            name=typed_form.name,
            signatures=typed_form.signatures,
            default_signature=typed_form.default_signature,
            capabilities=typed_form.capabilities,
            git=typed_form.git,
        )
        applied = apply_adoption(root, plan)
    return success(
        command,
        {
            "plan_id": applied.plan_id,
            "operation_count": applied.operation_count,
            "state_path": str(applied.state_path),
        },
        artifacts=(Artifact("managed-state", str(applied.state_path)),),
    )


def _form_from_arguments(
    args: argparse.Namespace, *, fallback_name: str | None = None
) -> ProjectForm:
    source = cast(str | None, args.form)
    if source is not None:
        return _read_form(source)
    name = cast(str | None, args.name) or fallback_name
    if name is None:
        raise CliUsageError("init requires NAME or --form FILE|-")
    signature_values = cast(list[str] | None, args.signature) or [Signature.SDK.value]
    default_value = cast(str | None, args.default_signature)
    return ProjectForm(
        name=name,
        signatures=tuple(Signature(value) for value in signature_values),
        default_signature=Signature(default_value) if default_value is not None else None,
        capabilities=tuple(cast(list[str], args.capabilities)),
        git=GitOptions(enabled=not cast(bool, args.no_git)),
    )


def _read_form(source: str) -> ProjectForm:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    return parse_project_form_json(raw)


def _migrate(args: argparse.Namespace) -> CommandEnvelope:
    action = cast(str, args.migrate_command)
    root = cast(Path, args.path)
    if action == "plan":
        source = cast(str | None, args.form)
        target = _read_form(source) if source is not None else None
        migration = plan_project_migration(root, target)
        return success("migrate plan", migration.document)
    if not cast(bool, args.yes):
        return failure(
            "migrate apply",
            5,
            Diagnostic(
                "KF-STATE-001",
                "error",
                "migration apply requires explicit --yes confirmation",
            ),
            refused=True,
        )
    plan_path = cast(Path, args.plan_file)
    migration = parse_migration_plan(plan_path.read_text(encoding="utf-8"))
    applied = apply_project_migration(root, migration)
    return success(
        "migrate apply",
        {
            "migration_id": migration.migration_id,
            "plan_id": applied.plan_id,
            "operation_count": applied.operation_count,
            "state_path": str(applied.state_path),
        },
        artifacts=(Artifact("managed-state", str(applied.state_path)),),
    )


def _check(root: Path) -> CommandEnvelope:
    state_path = root / ".kernform/state.json"
    manifest_schema = _manifest_schema(root)
    if not state_path.is_file():
        manifest = root / "kernform.toml"
        if manifest.is_file():
            if manifest_schema == LEGACY_PROJECT_SCHEMA:
                legacy = read_project_form(root, allow_legacy=True)
                return success(
                    "check",
                    {
                        "conformant": False,
                        "legacy_schema": LEGACY_PROJECT_SCHEMA,
                        "migration_required": True,
                        "mapped_signatures": [str(item) for item in legacy.signatures],
                        "managed_state": False,
                    },
                )
            versions = inspect_version_state(root)
            required = (
                "crates/kernform-core",
                "crates/kernform-engine",
                "crates/kernform-python",
                "python/kernform",
                "schemas",
            )
            missing = [path for path in required if not (root / path).exists()]
            if versions["conformant"] is True and not missing:
                return success(
                    "check",
                    {
                        "conformant": True,
                        "mode": "source-repository",
                        "catalog_hash": load_builtin_catalog().hash,
                    },
                )
            return CommandEnvelope(
                command="check",
                status="failure",
                exit_code=2,
                result={"versions": versions, "missing": missing},
                diagnostics=(
                    Diagnostic(
                        "KF-STATE-001",
                        "error",
                        "source repository conformance failed",
                    ),
                ),
            )
        return failure(
            "check",
            2,
            Diagnostic(
                "KF-STATE-001",
                "error",
                "managed state is missing",
                {"path": str(state_path)},
            ),
        )
    state_raw = state_path.read_text(encoding="utf-8")
    state_value: object = json.loads(state_raw)
    if not isinstance(state_value, dict):
        raise ValueError("managed state is not an object")
    state = cast(dict[str, object], state_value)
    file_values = state.get("files")
    if not isinstance(file_values, list):
        raise ValueError("managed state files is not an array")
    snapshot = inspect_repository(root, state_raw)
    changed: list[str] = []
    for item in cast(list[object], file_values):
        if not isinstance(item, dict):
            raise ValueError("managed state contains an invalid file entry")
        entry = cast(dict[str, object], item)
        path = entry.get("path")
        digest = entry.get("hash")
        if not isinstance(path, str) or not isinstance(digest, str):
            raise ValueError("managed state contains invalid file metadata")
        observed = snapshot.files.get(path)
        if observed is None or observed.hash != digest:
            changed.append(path)
    if changed:
        return failure(
            "check",
            2,
            Diagnostic(
                "KF-OWNERSHIP-001",
                "error",
                "managed files differ from recorded state",
                {"paths": sorted(changed)},
            ),
        )
    if manifest_schema == LEGACY_PROJECT_SCHEMA:
        legacy = read_project_form(root, allow_legacy=True)
        return success(
            "check",
            {
                "conformant": True,
                "legacy_schema": LEGACY_PROJECT_SCHEMA,
                "migration_required": True,
                "mapped_signatures": [str(item) for item in legacy.signatures],
                "files_checked": len(snapshot.files),
            },
        )
    if manifest_schema != PROJECT_FORM_SCHEMA or state.get("schema") != "kernform.state/v2":
        return failure(
            "check",
            2,
            Diagnostic(
                "KF-STATE-001",
                "error",
                "project form and managed state must use their v2 schemas",
                {
                    "project_form_schema": manifest_schema,
                    "state_schema": state.get("schema"),
                },
            ),
        )
    return success("check", {"conformant": True, "files_checked": len(snapshot.files)})


def _manifest_schema(root: Path) -> object:
    path = root / "kernform.toml"
    if not path.is_file():
        return None
    with path.open("rb") as source:
        document = cast(dict[str, object], tomllib.load(source))
    return document.get("schema")


def _doctor() -> CommandEnvelope:
    tools = {name: shutil.which(name) for name in ("git", "podman", "nu")}
    tools["kernform-native"] = version()
    required_missing = [name for name in ("git",) if tools[name] is None]
    if required_missing:
        return failure(
            "doctor",
            3,
            Diagnostic(
                "KF-ENV-001",
                "error",
                "required host dependency is missing",
                {"tools": required_missing},
            ),
        )
    return success("doctor", {"tools": tools})


def _versions(args: argparse.Namespace) -> CommandEnvelope:
    action = cast(str, args.versions_command)
    root = cast(Path, args.path)
    if action == "inspect":
        return success("versions inspect", inspect_version_state(root))
    if action == "check":
        result = inspect_version_state(root)
        if result["conformant"] is True:
            return success("versions check", result)
        return CommandEnvelope(
            command="versions check",
            status="failure",
            exit_code=2,
            result=result,
            diagnostics=(
                Diagnostic(
                    "KF-VERSION-001",
                    "error",
                    "recorded toolchains or lock inputs differ from the built-in catalog",
                ),
            ),
        )
    plan = plan_version_update(root)
    if action == "plan":
        return success("versions plan", plan.document)
    if not cast(bool, args.accept):
        return failure(
            "versions update",
            5,
            Diagnostic(
                "KF-VERSION-001",
                "error",
                "version update requires --accept and the full test tier",
                {"catalog_hash": load_builtin_catalog().hash},
            ),
            refused=True,
        )
    applied = apply_adoption(root.resolve(strict=True), plan)
    return success(
        "versions update",
        {
            "plan_id": applied.plan_id,
            "operation_count": applied.operation_count,
            "state_path": str(applied.state_path),
            "requires_test_tier": "full",
        },
    )


def _release(args: argparse.Namespace) -> CommandEnvelope:
    action = cast(str, args.action)
    root = cast(Path, args.path)
    if action == "inspect":
        return success("release inspect", to_jsonable(release_inspect(root)))
    if action == "build":
        state = release_inspect(root)
        if state.phase is not ReleasePhase.VERIFIED:
            raise KernformPreconditionError("release build requires verified local release state")
        report = run_tier(root, "full")
        if report["status"] != "passed":
            return CommandEnvelope(
                command="release build",
                status="failure",
                exit_code=2,
                result=report,
                diagnostics=(
                    Diagnostic("KF-TEST-001", "error", "full release verification failed"),
                ),
            )
        artifact_directory = root / "target/kernform-test/wheels"
        export_oci_image(root, version=state.version, output_directory=artifact_directory)
        bundle = build_release_bundle(
            root,
            version=state.version,
            source_commit=state.source_commit,
            wheel_directory=artifact_directory,
            output_directory=root / "target/release",
        )
        return success(
            "release build",
            {
                "source_commit": state.source_commit,
                "bundle": str(bundle),
                "publication": "explicit",
            },
            artifacts=(Artifact("release-bundle", str(bundle)),),
        )
    if action in {"start", "finalize"} and not cast(bool, args.yes):
        return failure(
            f"release {action}",
            5,
            Diagnostic(
                "KF-GIT-001",
                "error",
                f"release {action} requires explicit --yes confirmation",
            ),
            refused=True,
        )
    if action == "start":
        release_version = cast(str | None, args.version)
        if release_version is None:
            raise CliUsageError("release start requires a version")
        state = release_start(root, release_version, load_builtin_catalog().hash)
    elif action == "verify":
        state = release_verify(
            root,
            metadata_matches=cast(bool, args.metadata_matches),
            synchronized=cast(bool, args.synchronized),
        )
    else:
        state = release_finalize(
            root,
            verification_complete=cast(bool, args.verification_complete),
        )
    return success(f"release {action}", to_jsonable(state))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and emit exactly one selected rendering."""
    arguments = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    output_format = OutputFormat.JSON if "--agent" in arguments else OutputFormat.HUMAN
    try:
        args = parser.parse_args(arguments)
        agent = cast(bool, args.agent)
        requested_format = cast(str | None, args.format)
        output_format = OutputFormat(requested_format or ("json" if agent else "human"))
        envelope = dispatch(args)
    except CliUsageError as error:
        agent = "--agent" in arguments
        output_format = OutputFormat.JSON if agent else OutputFormat.HUMAN
        envelope = failure(
            "usage",
            1,
            Diagnostic("KF-BOUNDARY-001", "error", str(error)),
        )
    except KernformPreconditionError as error:
        envelope = failure(
            _command_name(arguments),
            2,
            Diagnostic("KF-STATE-001", "error", str(error)),
        )
    except KernformProcessError as error:
        envelope = failure(
            _command_name(arguments),
            3,
            Diagnostic("KF-ENV-001", "error", str(error)),
        )
    except KernformPolicyError as error:
        envelope = failure(
            _command_name(arguments),
            5,
            Diagnostic("KF-BOUNDARY-001", "error", str(error)),
            refused=True,
        )
    except (KernformNativeError, OSError, ValueError) as error:
        envelope = failure(
            _command_name(arguments),
            4,
            Diagnostic("KF-INTERNAL-001", "error", str(error)),
        )
    print(render(envelope, output_format))
    return envelope.exit_code


def _command_name(arguments: Sequence[str]) -> str:
    return next((argument for argument in arguments if not argument.startswith("-")), "usage")


if __name__ == "__main__":
    raise SystemExit(main())
