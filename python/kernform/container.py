"""Rootless Podman orchestration with worktree-scoped resource identities."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from kernform.errors import KernformPolicyError, KernformPreconditionError
from kernform.process import ProcessOutcome, run_checked, run_process

_NAME_PATTERN = re.compile(r"[^a-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class ContainerContext:
    """Deterministic Podman identities for one physical worktree."""

    root: Path
    project: str
    worktree_hash: str
    image: str
    runtime_name: str
    development_name: str
    test_name: str
    network_name: str
    cache_volume_name: str
    temporary_name: str
    host_port: int

    def document(self) -> dict[str, object]:
        """Return the public identity document."""
        return {
            "root": str(self.root),
            "project": self.project,
            "worktree_hash": self.worktree_hash,
            "image": self.image,
            "runtime_name": self.runtime_name,
            "development_name": self.development_name,
            "test_name": self.test_name,
            "network_name": self.network_name,
            "cache_volume_name": self.cache_volume_name,
            "temporary_name": self.temporary_name,
            "host_port": self.host_port,
        }


def container_context(root: Path) -> ContainerContext:
    """Derive collision-resistant local names from the canonical worktree path."""
    canonical = root.resolve(strict=True)
    if not (canonical / "containers/Containerfile").is_file():
        raise KernformPreconditionError(
            f"container capability is missing: {canonical / 'containers/Containerfile'}"
        )
    project = _NAME_PATTERN.sub("-", canonical.name.lower()).strip("-.") or "kernform"
    worktree_hash = hashlib.sha256(str(canonical).encode()).hexdigest()[:12]
    prefix = f"{project}-{worktree_hash}"
    host_port = 20_000 + int(worktree_hash[:4], 16) % 20_000
    return ContainerContext(
        canonical,
        project,
        worktree_hash,
        f"localhost/{project}:{worktree_hash}",
        f"{prefix}-runtime",
        f"{prefix}-dev",
        f"{prefix}-test",
        f"{prefix}-network",
        f"{prefix}-cache",
        f"{prefix}-tmp",
        host_port,
    )


def inspect_podman(root: Path) -> dict[str, object]:
    """Inspect the host and refuse a privileged Podman service."""
    context = container_context(root)
    result = run_checked(
        ("podman", "info", "--format", "json"),
        cwd=context.root,
        timeout_seconds=30,
    )
    value: object = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise KernformPolicyError("podman info did not return an object")
    document = cast(dict[str, object], value)
    host_value = document.get("host")
    host = cast(dict[str, object], host_value) if isinstance(host_value, dict) else {}
    security_value = host.get("security")
    security = cast(dict[str, object], security_value) if isinstance(security_value, dict) else {}
    rootless = security.get("rootless")
    if rootless is not True:
        raise KernformPolicyError("Kernform container operations require rootless Podman")
    version_value = document.get("version")
    version = cast(dict[str, object], version_value) if isinstance(version_value, dict) else {}
    observed_version = version.get("Version")
    return {**context.document(), "rootless": True, "podman_version": observed_version}


def container_operation(root: Path, action: str) -> dict[str, object]:
    """Build, run, inspect, or test the generated container targets."""
    host = inspect_podman(root)
    context = container_context(root)
    if action == "inspect":
        exists = (
            run_process(
                ("podman", "container", "exists", context.runtime_name),
                cwd=context.root,
                timeout_seconds=15,
            ).exit_code
            == 0
        )
        return {**host, "container_exists": exists}
    if action == "build":
        result = _build(context, "runtime", context.image)
    elif action == "test":
        result = _build(context, "ci", f"{context.image}-ci")
    elif action == "run":
        _build(context, "runtime", context.image)
        _ensure_network(context)
        result = run_checked(
            (
                "podman",
                "run",
                "--detach",
                "--replace",
                "--name",
                context.runtime_name,
                "--label",
                f"io.kernform.worktree={context.worktree_hash}",
                "--read-only",
                "--user",
                "65532:65532",
                "--security-opt",
                "no-new-privileges",
                "--cap-drop",
                "all",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                "--network",
                context.network_name,
                "--publish",
                f"127.0.0.1:{context.host_port}:8000",
                context.image,
            ),
            cwd=context.root,
            timeout_seconds=120,
        )
    else:
        raise ValueError(f"unsupported container action: {action}")
    return {**host, "action": action, "process": _summary(result)}


def development_operation(root: Path, action: str) -> dict[str, object]:
    """Manage one isolated development container for the current worktree."""
    host = inspect_podman(root)
    context = container_context(root)
    image = f"{context.image}-dev"
    if action == "up":
        _build(context, "dev-human", image)
        _ensure_network(context)
        result = run_checked(
            (
                "podman",
                "run",
                "--detach",
                "--replace",
                "--name",
                context.development_name,
                "--label",
                f"io.kernform.worktree={context.worktree_hash}",
                "--read-only",
                "--security-opt",
                "no-new-privileges",
                "--cap-drop",
                "all",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                "--tmpfs",
                "/workspace/target:rw,nosuid,size=2g",
                "--network",
                context.network_name,
                "--volume",
                f"{context.cache_volume_name}:/workspace/.cache:rw",
                image,
                "sleep",
                "infinity",
            ),
            cwd=context.root,
            timeout_seconds=120,
        )
    elif action == "down":
        result = run_checked(
            ("podman", "rm", "--force", "--ignore", context.development_name),
            cwd=context.root,
            timeout_seconds=60,
        )
    elif action == "reset":
        run_checked(
            ("podman", "rm", "--force", "--ignore", context.development_name),
            cwd=context.root,
            timeout_seconds=60,
        )
        result = run_checked(
            ("podman", "image", "rm", "--force", "--ignore", image),
            cwd=context.root,
            timeout_seconds=60,
        )
    elif action == "logs":
        result = run_checked(
            ("podman", "logs", context.development_name),
            cwd=context.root,
            timeout_seconds=30,
        )
    else:
        raise ValueError(f"unsupported development action: {action}")
    return {**host, "action": action, "process": _summary(result)}


def _build(context: ContainerContext, target: str, image: str) -> ProcessOutcome:
    return run_checked(
        (
            "podman",
            "build",
            "--file",
            "containers/Containerfile",
            "--target",
            target,
            "--tag",
            image,
            "--label",
            f"io.kernform.worktree={context.worktree_hash}",
            ".",
        ),
        cwd=context.root,
        timeout_seconds=1800,
    )


def _ensure_network(context: ContainerContext) -> None:
    run_checked(
        ("podman", "network", "create", "--ignore", context.network_name),
        cwd=context.root,
        timeout_seconds=30,
    )


def _summary(result: ProcessOutcome) -> dict[str, object]:
    return {
        "argv": list(result.argv),
        "exit_code": result.exit_code,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }
