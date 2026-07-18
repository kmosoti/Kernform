from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest

import kernform

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.deep
def test_planning_stays_deterministic_across_many_valid_names() -> None:
    for index in range(100):
        name = f"contract-{index}"
        first = kernform.plan_project(name=name, profile=kernform.Profile.LIBRARY)
        second = kernform.plan_project(name=name, profile=kernform.Profile.LIBRARY)
        assert first.json == second.json


@pytest.mark.deep
def test_parallel_planning_stress_is_byte_equivalent() -> None:
    def plan(_: int) -> str:
        return kernform.plan_project(
            name="parallel-contract", profile=kernform.Profile.LIBRARY
        ).json

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(plan, range(128)))
    assert len(set(results)) == 1


@pytest.mark.deep
def test_planner_performance_canary() -> None:
    value: object = json.loads((ROOT / "fixtures/baselines/planner.json").read_text())
    assert isinstance(value, dict)
    baseline = cast(dict[str, object], value)
    maximum = baseline.get("maximum_seconds")
    assert isinstance(maximum, float)
    started = time.perf_counter()
    for index in range(1000):
        kernform.plan_project(name=f"perf-{index}", profile=kernform.Profile.LIBRARY)
    assert time.perf_counter() - started < maximum
