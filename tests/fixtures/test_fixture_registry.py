from __future__ import annotations

import json
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]


def test_required_project_scenarios_are_declared() -> None:
    value: object = json.loads((ROOT / "fixtures/projects/scenarios.json").read_text())
    assert isinstance(value, dict)
    document = cast(dict[str, object], value)
    scenarios_value = document.get("scenarios")
    assert isinstance(scenarios_value, list)
    scenarios = cast(list[object], scenarios_value)
    identifiers: set[str] = set()
    for scenario_value in scenarios:
        assert isinstance(scenario_value, dict)
        scenario = cast(dict[str, object], scenario_value)
        identifier = scenario.get("id")
        assert isinstance(identifier, str)
        identifiers.add(identifier)
    assert identifiers == {
        "empty",
        "python-only",
        "existing-git",
        "existing-pyo3",
        "conflicting",
        "modified-ownership",
        "missing-identity",
        "offline",
    }
