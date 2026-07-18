from __future__ import annotations

import shutil
from pathlib import Path
from typing import cast

from _pytest.monkeypatch import MonkeyPatch

import kernform.testing as testing_module
from kernform.process import ProcessOutcome
from kernform.testing import TIER_PLANS, TierStep, run_tier, tier_plan


def test_tier_membership_is_explicit_and_hierarchical() -> None:
    assert set(TIER_PLANS) == {"fast", "full", "deep"}
    fast_static = {step.id for step in TIER_PLANS["fast"] if step.id != "python-fast-tests"}
    full_ids = {step.id for step in TIER_PLANS["full"]}
    deep_ids = {step.id for step in TIER_PLANS["deep"]}
    assert fast_static < full_ids < deep_ids


def test_test_plan_is_machine_readable_and_argv_only() -> None:
    document = tier_plan("full")
    assert document["schema"] == "kernform.test-tier/v1"
    assert document["tier"] == "full"
    steps_value = document["steps"]
    assert isinstance(steps_value, list)
    steps = cast(list[object], steps_value)
    arguments: list[str] = []
    for step_value in steps:
        assert isinstance(step_value, dict)
        step = cast(dict[str, object], step_value)
        argv_value = step["argv"]
        assert isinstance(argv_value, list)
        argv = cast(list[object], argv_value)
        assert all(isinstance(argument, str) for argument in argv)
        arguments.extend(cast(list[str], argv))
    assert not any(argument in {"sh", "bash", "-c"} for argument in arguments)


def test_optional_tool_proxy_with_failed_probe_is_reported_as_skipped(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    step = TierStep("optional-proxy", ("optional-proxy", "scan"), 60, optional=True)
    monkeypatch.setitem(TIER_PLANS, "probe", (step,))

    def fake_which(program: str) -> str:
        assert program == "optional-proxy"
        return "/usr/bin/optional-proxy"

    monkeypatch.setattr(shutil, "which", fake_which)

    def fake_process(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: int,
        environment: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> ProcessOutcome:
        del cwd, timeout_seconds, environment, input_text
        assert argv == ("optional-proxy", "--version")
        return ProcessOutcome(argv, 1, "", "component unavailable")

    monkeypatch.setattr(testing_module, "run_process", fake_process)
    report = run_tier(tmp_path, "probe")
    assert report["status"] == "passed"
    steps = cast(list[dict[str, object]], report["steps"])
    assert steps[0]["status"] == "skipped"
    assert "component unavailable" in cast(str, steps[0]["reason"])
