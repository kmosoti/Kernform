from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker

# pyright: reportUnknownMemberType=false

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"
FIXTURES = ROOT / "fixtures" / "contracts"
CONTRACTS = ("kernform", "state", "plan", "command")


def load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.fast
@pytest.mark.parametrize("contract", CONTRACTS)
def test_valid_contract_fixture(contract: str) -> None:
    schema = load_json(SCHEMAS / f"{contract}.schema.json")
    fixture = load_json(FIXTURES / "valid" / f"{contract}.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(fixture)


@pytest.mark.fast
@pytest.mark.parametrize("contract", CONTRACTS)
def test_invalid_contract_fixture(contract: str) -> None:
    schema = load_json(SCHEMAS / f"{contract}.schema.json")
    fixture = load_json(FIXTURES / "invalid" / f"{contract}.json")
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(fixture))
    assert errors, f"invalid {contract} fixture unexpectedly passed"


@pytest.mark.fast
def test_repository_manifest_conforms() -> None:
    with (ROOT / "kernform.toml").open("rb") as source:
        manifest = tomllib.load(source)
    schema = load_json(SCHEMAS / "kernform.schema.json")
    Draft202012Validator(schema).validate(manifest)


@pytest.mark.fast
def test_valid_examples_have_deterministic_json_encoding() -> None:
    for contract in CONTRACTS:
        fixture = load_json(FIXTURES / "valid" / f"{contract}.json")
        first = json.dumps(fixture, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        second = json.dumps(
            json.loads(first), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        assert first == second


@pytest.mark.fast
def test_closed_manifest_rejects_unknown_values() -> None:
    fixture = load_json(FIXTURES / "valid" / "kernform.json")
    fixture["unknown"] = True
    schema = load_json(SCHEMAS / "kernform.schema.json")
    assert list(Draft202012Validator(schema).iter_errors(fixture))
