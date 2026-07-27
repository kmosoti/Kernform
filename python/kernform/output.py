"""Stable command envelopes and deterministic renderers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast


def _empty_context() -> dict[str, object]:
    return {}


class OutputFormat(StrEnum):
    """Supported CLI rendering formats."""

    HUMAN = "human"
    JSON = "json"
    NUON = "nuon"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Stable command diagnostic."""

    id: str
    severity: str
    message: str
    context: dict[str, object] = field(default_factory=_empty_context)


@dataclass(frozen=True, slots=True)
class Artifact:
    """Stable command artifact reference."""

    kind: str
    path: str
    hash: str | None = None


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    """Stable `kernform.command/v2` result."""

    command: str
    status: str
    exit_code: int
    result: object
    diagnostics: tuple[Diagnostic, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    schema: str = "kernform.command/v2"

    def document(self) -> dict[str, object]:
        """Return the exact schema-shaped object."""
        return {
            "schema": self.schema,
            "command": self.command,
            "status": self.status,
            "exit_code": self.exit_code,
            "result": self.result,
            "diagnostics": [
                {
                    "id": diagnostic.id,
                    "severity": diagnostic.severity,
                    "message": diagnostic.message,
                    "context": diagnostic.context,
                }
                for diagnostic in self.diagnostics
            ],
            "artifacts": [
                {"kind": artifact.kind, "path": artifact.path, "hash": artifact.hash}
                for artifact in self.artifacts
            ],
        }


def success(command: str, result: object, artifacts: tuple[Artifact, ...] = ()) -> CommandEnvelope:
    """Build a successful command result."""
    return CommandEnvelope(command, "success", 0, result, artifacts=artifacts)


def failure(
    command: str,
    exit_code: int,
    diagnostic: Diagnostic,
    *,
    refused: bool = False,
) -> CommandEnvelope:
    """Build a failed or policy-refused command result."""
    return CommandEnvelope(
        command,
        "refused" if refused else "failure",
        exit_code,
        None,
        diagnostics=(diagnostic,),
    )


def render(envelope: CommandEnvelope, output_format: OutputFormat) -> str:
    """Render without color, paging, timestamps, or unstable decorations."""
    if output_format in {OutputFormat.JSON, OutputFormat.NUON}:
        return json.dumps(envelope.document(), sort_keys=True, separators=(",", ":"))
    if envelope.status == "success":
        if isinstance(envelope.result, str):
            return envelope.result
        return json.dumps(envelope.result, indent=2, sort_keys=True)
    diagnostic = envelope.diagnostics[0]
    return f"{diagnostic.id}: {diagnostic.message}"


def parse_envelope(raw: str) -> dict[str, object]:
    """Decode renderer output in tests and embedding clients."""
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("command envelope is not an object")
    return cast(dict[str, object], value)
