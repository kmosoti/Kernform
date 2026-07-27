from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from kernform.cli import build_parser
from kernform.models import Ownership, ReleasePhase, Signature
from kernform.output import OutputFormat

ROOT = Path(__file__).resolve().parents[2]


def test_frozen_schema_identifiers() -> None:
    expected = {
        "kernform": "urn:kernform:schema:project-form:v2",
        "state": "urn:kernform:schema:state:v2",
        "plan": "urn:kernform:schema:plan:v2",
        "command": "urn:kernform:schema:command:v2",
    }
    observed: dict[str, object] = {}
    for name in expected:
        value: object = json.loads((ROOT / f"schemas/{name}.schema.json").read_text())
        assert isinstance(value, dict)
        document = cast(dict[str, object], value)
        observed[name] = document.get("$id")
    assert observed == expected


def test_frozen_public_enumerations() -> None:
    assert tuple(Signature) == (
        Signature.SDK,
        Signature.CLI,
        Signature.API,
        Signature.INTERACTIVE_WEB,
        Signature.DAEMON,
    )
    assert tuple(Ownership) == (
        Ownership.MANAGED,
        Ownership.SEEDED,
        Ownership.GENERATED,
        Ownership.USER,
        Ownership.EXTERNAL,
    )
    assert tuple(ReleasePhase) == (
        ReleasePhase.IDLE,
        ReleasePhase.STARTED,
        ReleasePhase.VERIFIED,
        ReleasePhase.FINALIZED,
    )
    assert tuple(OutputFormat) == (OutputFormat.HUMAN, OutputFormat.JSON, OutputFormat.NUON)


def test_frozen_command_groups() -> None:
    parser = build_parser()
    command_action = next(action for action in parser._actions if action.dest == "command")
    choices = getattr(command_action, "choices", None)
    assert isinstance(choices, dict)
    typed_choices = cast(dict[str, object], choices)
    assert tuple(typed_choices) == (
        "compile",
        "init",
        "adopt",
        "migrate",
        "scaffold",
        "inspect",
        "check",
        "doctor",
        "test",
        "versions",
        "container",
        "dev",
        "shell",
        "release",
    )


def test_frozen_diagnostic_identifiers_are_documented_and_used() -> None:
    expected = {
        "KF-ARCH-001",
        "KF-BOUNDARY-001",
        "KF-ENV-001",
        "KF-GIT-001",
        "KF-INTERNAL-001",
        "KF-OWNERSHIP-001",
        "KF-STATE-001",
        "KF-TEST-001",
        "KF-VERSION-001",
        "KF-WEB-001",
    }
    documentation = (ROOT / "docs/standards/diagnostics.md").read_text(encoding="utf-8")
    assert all(identifier in documentation for identifier in expected)
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (ROOT / "crates", ROOT / "python")
        for path in root.rglob("*")
        if path.suffix in {".rs", ".py"}
    )
    assert all(identifier in source for identifier in expected)
