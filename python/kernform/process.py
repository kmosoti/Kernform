"""Structured host-process boundary used by Python orchestration surfaces."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from kernform.errors import KernformProcessError


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    """Captured result of one argv-only process execution."""

    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str

    def document(self) -> dict[str, object]:
        """Return a compact machine-readable representation."""
        return {
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def run_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    timeout_seconds: int,
    environment: dict[str, str] | None = None,
    input_text: str | None = None,
) -> ProcessOutcome:
    """Run explicit argv without a shell and capture deterministic text streams."""
    if not argv or not argv[0].strip() or timeout_seconds <= 0:
        raise KernformProcessError("program and a positive timeout are required")
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=environment or os.environ.copy(),
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        raise KernformProcessError(f"required program is unavailable: {argv[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise KernformProcessError(
            f"program timed out after {timeout_seconds} seconds: {argv[0]}"
        ) from error
    return ProcessOutcome(argv, completed.returncode, completed.stdout, completed.stderr)


def run_checked(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    timeout_seconds: int,
    environment: dict[str, str] | None = None,
    input_text: str | None = None,
) -> ProcessOutcome:
    """Run one process and raise the stable environment error for nonzero status."""
    result = run_process(
        argv,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        environment=environment,
        input_text=input_text,
    )
    if result.exit_code != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise KernformProcessError(
            f"{argv[0]} exited with status {result.exit_code}: {detail[-1000:]}"
        )
    return result


def run_attached(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    timeout_seconds: int,
    environment: dict[str, str] | None = None,
) -> ProcessOutcome:
    """Run explicit argv with the caller's terminal streams attached."""
    if not argv or not argv[0].strip() or timeout_seconds <= 0:
        raise KernformProcessError("program and a positive timeout are required")
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=environment or os.environ.copy(),
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        raise KernformProcessError(f"required program is unavailable: {argv[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise KernformProcessError(
            f"program timed out after {timeout_seconds} seconds: {argv[0]}"
        ) from error
    return ProcessOutcome(argv, completed.returncode, "", "")
