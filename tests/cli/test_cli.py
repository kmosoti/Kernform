from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from _pytest.capture import CaptureFixture
from jsonschema import Draft202012Validator

from kernform.cli import build_parser, dispatch, main

ROOT = Path(__file__).resolve().parents[2]
COMMAND_SCHEMA = json.loads((ROOT / "schemas/command.schema.json").read_text())


def parsed(*arguments: str) -> Namespace:
    return build_parser().parse_args(list(arguments))


def test_json_command_envelope_validates(capsys: CaptureFixture[str]) -> None:
    assert main(["--format", "json", "versions", "inspect"]) == 0
    document = json.loads(capsys.readouterr().out)
    Draft202012Validator(COMMAND_SCHEMA).validate(document)  # pyright: ignore[reportUnknownMemberType]
    assert document["command"] == "versions inspect"


def test_agent_mode_is_single_line_json_and_never_prompts(
    capsys: CaptureFixture[str],
) -> None:
    assert main(["--agent", "versions", "inspect"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    assert json.loads(captured.out)["schema"] == "kernform.command/v2"


def test_cli_dispatch_matches_direct_dispatch(capsys: CaptureFixture[str]) -> None:
    args = parsed("--format", "json", "inspect", str(ROOT))
    direct = dispatch(args).document()
    assert main(["--format", "json", "inspect", str(ROOT)]) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered == direct


def test_adopt_requires_explicit_confirmation(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    envelope = dispatch(parsed("adopt", str(tmp_path), "--plan-file", str(plan)))
    assert envelope.status == "refused"
    assert envelope.exit_code == 5


def test_all_public_command_groups_parse() -> None:
    samples = [
        ["compile", "--form", "form.json"],
        ["init", "example"],
        ["migrate", "plan", "."],
        ["scaffold", "module", "example"],
        ["inspect"],
        ["check"],
        ["doctor"],
        ["test", "fast"],
        ["versions", "check"],
        ["container", "inspect"],
        ["dev", "logs"],
        ["shell", "agent"],
        ["release", "inspect"],
    ]
    assert all(build_parser().parse_args(sample).command for sample in samples)
