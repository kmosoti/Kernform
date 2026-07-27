"""Machine-readable cross-language verification tier orchestration."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from kernform.process import run_process


@dataclass(frozen=True, slots=True)
class TierStep:
    """One maintained argv-only tier member."""

    id: str
    argv: tuple[str, ...]
    timeout_seconds: int
    optional: bool = False
    environment: tuple[tuple[str, str], ...] = ()

    def document(self) -> dict[str, object]:
        """Return the stable tier declaration."""
        return {
            "id": self.id,
            "argv": list(self.argv),
            "timeout_seconds": self.timeout_seconds,
            "optional": self.optional,
            "environment": dict(self.environment),
        }


_STATIC_STEPS = (
    TierStep("rust-format", ("cargo", "fmt", "--all", "--", "--check"), 120),
    TierStep(
        "rust-lint",
        (
            "cargo",
            "clippy",
            "--workspace",
            "--all-targets",
            "--all-features",
            "--locked",
            "--",
            "-D",
            "warnings",
        ),
        900,
    ),
    TierStep(
        "rust-tests",
        ("cargo", "test", "--workspace", "--all-features", "--locked"),
        900,
    ),
    TierStep(
        "rust-docs",
        ("cargo", "doc", "--workspace", "--all-features", "--locked", "--no-deps"),
        600,
    ),
    TierStep("python-lint", ("uv", "run", "ruff", "check", "python", "tests"), 180),
    TierStep(
        "python-format",
        ("uv", "run", "ruff", "format", "--check", "python", "tests"),
        180,
    ),
    TierStep("python-types", ("uv", "run", "pyright"), 300),
)

_FAST = (
    *_STATIC_STEPS,
    TierStep(
        "python-fast-tests",
        ("uv", "run", "pytest", "-m", "not full and not deep"),
        900,
    ),
)

_FULL = (
    *_STATIC_STEPS,
    TierStep("python-full-tests", ("uv", "run", "pytest", "-m", "not deep"), 1800),
    TierStep(
        "container-signature-matrix",
        ("uv", "run", "pytest", "tests/containers", "-m", "container"),
        3600,
        environment=(("KERNFORM_CONTAINER_SMOKE", "1"),),
    ),
    TierStep(
        "wheel-build",
        ("uv", "build", "--out-dir", "target/kernform-test/wheels"),
        1200,
    ),
    TierStep(
        "wheel-clean-install",
        ("uv", "run", "python", "-m", "kernform.wheel_verify"),
        600,
    ),
)

_DEEP = (
    *_FULL,
    TierStep(
        "rust-release-tests",
        ("cargo", "test", "--workspace", "--all-features", "--release", "--locked"),
        1800,
    ),
    TierStep("python-deep-tests", ("uv", "run", "pytest", "-m", "deep"), 1200),
    TierStep("rust-audit", ("cargo-audit", "audit", "--locked"), 900, optional=True),
    TierStep(
        "rust-fuzz",
        ("cargo-fuzz", "run", "planner", "--", "-max_total_time=60"),
        300,
        optional=True,
    ),
    TierStep(
        "rust-miri",
        ("cargo-miri", "test", "-p", "kernform-core"),
        1200,
        optional=True,
    ),
    TierStep("rust-mutation", ("cargo-mutants", "--check"), 1800, optional=True),
    TierStep("python-audit", ("pip-audit", "--strict"), 900, optional=True),
    TierStep("python-security", ("semgrep", "scan", "--config", "auto"), 1200, optional=True),
)

TIER_PLANS: dict[str, tuple[TierStep, ...]] = {
    "fast": _FAST,
    "full": _FULL,
    "deep": _DEEP,
}


def tier_plan(tier: str) -> dict[str, object]:
    """Return explicit machine-readable membership without running commands."""
    steps = TIER_PLANS.get(tier)
    if steps is None:
        raise ValueError(f"unknown test tier: {tier}")
    return {
        "schema": "kernform.test-tier/v1",
        "tier": tier,
        "steps": [step.document() for step in steps],
    }


def run_tier(root: Path, tier: str) -> dict[str, object]:
    """Run one tier in declaration order and retain bounded evidence."""
    canonical = root.resolve(strict=True)
    steps = TIER_PLANS.get(tier)
    if steps is None:
        raise ValueError(f"unknown test tier: {tier}")
    results: list[dict[str, object]] = []
    passed = True
    for step in steps:
        unavailable = _optional_unavailable(canonical, step)
        if unavailable is not None:
            results.append(
                {
                    **step.document(),
                    "status": "skipped",
                    "reason": unavailable,
                }
            )
            continue
        outcome = run_process(
            step.argv,
            cwd=canonical,
            timeout_seconds=step.timeout_seconds,
            environment=_step_environment(step),
        )
        status = "passed" if outcome.exit_code == 0 else "failed"
        results.append(
            {
                **step.document(),
                "status": status,
                "exit_code": outcome.exit_code,
                "stdout_tail": outcome.stdout[-4000:],
                "stderr_tail": outcome.stderr[-4000:],
            }
        )
        if outcome.exit_code != 0:
            passed = False
            break
    return {
        "schema": "kernform.test-report/v1",
        "tier": tier,
        "status": "passed" if passed else "failed",
        "steps": results,
    }


def _step_environment(step: TierStep) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(dict(step.environment))
    return environment


def _optional_unavailable(root: Path, step: TierStep) -> str | None:
    if not step.optional:
        return None
    if shutil.which(step.argv[0]) is None:
        return f"optional program unavailable: {step.argv[0]}"
    probe = run_process(
        (step.argv[0], "--version"),
        cwd=root,
        timeout_seconds=30,
        environment=_step_environment(step),
    )
    if probe.exit_code == 0:
        return None
    detail = probe.stderr.strip() or probe.stdout.strip() or "version probe failed"
    return f"optional program unusable: {step.argv[0]}: {detail[-500:]}"
