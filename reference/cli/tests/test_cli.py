import json

from _pytest.capture import CaptureFixture

from example_cli.cli import main


def test_agent_output_is_parseable(capsys: CaptureFixture[str]) -> None:
    assert main(["20", "22", "--agent"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {"result": 42}


def test_completion_is_explicit_and_static(capsys: CaptureFixture[str]) -> None:
    assert main(["--completion", "nushell"]) == 0
    assert 'export extern "example-cli"' in capsys.readouterr().out
