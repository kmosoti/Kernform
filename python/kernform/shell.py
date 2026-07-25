"""Separated Nushell launch boundaries for humans and agents."""

from __future__ import annotations

import os
from pathlib import Path

from kernform.errors import KernformPreconditionError, KernformProcessError
from kernform.process import run_attached, run_process

_AGENT_ENV_ALLOWLIST = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "PATH",
    "USER",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_RUNTIME_DIR",
)


def shell_operation(root: Path, mode: str, *, interactive: bool = False) -> dict[str, object]:
    """Launch the selected configuration with explicit stdin and bounded execution."""
    canonical = root.resolve(strict=True)
    config = canonical / "shell" / mode / "config.nu"
    environment_config = canonical / "shell" / mode / "env.nu"
    if mode not in {"human", "agent"}:
        raise ValueError(f"unsupported shell mode: {mode}")
    if not config.is_file() or not environment_config.is_file():
        raise KernformPreconditionError(f"Nushell {mode} capability is not installed")

    argv = (
        "nu",
        "--config",
        str(config),
        "--env-config",
        str(environment_config),
        "--no-history",
    )
    environment = shell_environment(mode)
    timeout_seconds = 120 if mode == "agent" else 300
    if interactive:
        if mode != "human":
            raise ValueError("agent shell mode cannot be interactive")
        result = run_attached(
            argv,
            cwd=canonical,
            timeout_seconds=timeout_seconds,
            environment=environment,
        )
    else:
        result = run_process(
            argv,
            cwd=canonical,
            timeout_seconds=timeout_seconds,
            environment=environment,
            input_text="exit 0\n",
        )
    if result.exit_code != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise KernformProcessError(
            f"Nushell {mode} mode exited with status {result.exit_code}: {detail[-1000:]}"
        )
    return {
        "mode": mode,
        "argv": list(argv),
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "environment_policy": "allowlist" if mode == "agent" else "inherited",
        "interactive": interactive,
    }


def shell_environment(mode: str) -> dict[str, str]:
    """Return inherited human or allowlisted agent environment state."""
    if mode == "human":
        return os.environ.copy()
    environment = {
        name: value for name in _AGENT_ENV_ALLOWLIST if (value := os.environ.get(name)) is not None
    }
    environment.update(
        {
            "KERNFORM_MODE": "agent",
            "KERNFORM_TIMEOUT_SECONDS": "120",
            "NO_COLOR": "1",
            "PAGER": "cat",
            "TERM": "dumb",
        }
    )
    return environment
