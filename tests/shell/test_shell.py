from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

import kernform.shell as shell_module
from kernform.errors import KernformProcessError
from kernform.process import ProcessOutcome
from kernform.shell import shell_environment, shell_operation

ROOT = Path(__file__).resolve().parents[2]


def test_agent_environment_is_allowlisted(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("KERNFORM_TEST_SECRET", "must-not-pass")
    environment = shell_environment("agent")
    assert "KERNFORM_TEST_SECRET" not in environment
    assert environment["KERNFORM_MODE"] == "agent"
    assert environment["NO_COLOR"] == "1"
    assert environment["PAGER"] == "cat"
    assert environment["TERM"] == "dumb"


def test_agent_module_forces_machine_mode_and_propagates_exit_status() -> None:
    content = (ROOT / "shell/agent/config.nu").read_text(encoding="utf-8")
    assert "^kernform --agent ...$args | complete" in content
    assert "$process.exit_code" in content
    assert "from json" in content
    assert "use ../modules/kf" not in content


@pytest.mark.parametrize("mode", ["human", "agent"])
def test_shell_launch_preserves_paths_as_single_argv_values(
    tmp_path: Path, monkeypatch: MonkeyPatch, mode: str
) -> None:
    root = tmp_path / "project with spaces"
    config_root = root / "shell" / mode
    config_root.mkdir(parents=True)
    (config_root / "config.nu").write_text("$env.TEST = true\n", encoding="utf-8")
    (config_root / "env.nu").write_text("$env.TEST_MODE = 'yes'\n", encoding="utf-8")
    observed: list[tuple[str, ...]] = []

    def fake_process(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: int,
        environment: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> ProcessOutcome:
        del cwd, environment
        assert timeout_seconds == (120 if mode == "agent" else 300)
        assert input_text == "exit 0\n"
        observed.append(argv)
        return ProcessOutcome(argv, 0, "", "")

    monkeypatch.setattr(shell_module, "run_process", fake_process)
    result = shell_operation(root, mode)
    assert result["exit_code"] == 0
    assert str(config_root / "config.nu") in observed[0]
    assert str(config_root / "env.nu") in observed[0]
    assert not any(value in {"sh", "bash", "-c", "--commands"} for value in observed[0])


def test_human_terminal_launch_attaches_streams(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    root = tmp_path / "project"
    config_root = root / "shell" / "human"
    config_root.mkdir(parents=True)
    (config_root / "config.nu").write_text("$env.TEST = true\n", encoding="utf-8")
    (config_root / "env.nu").write_text("$env.TEST_MODE = 'yes'\n", encoding="utf-8")
    observed: list[tuple[str, ...]] = []

    def fake_attached(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: int,
        environment: dict[str, str] | None = None,
    ) -> ProcessOutcome:
        del cwd, environment
        assert timeout_seconds == 300
        observed.append(argv)
        return ProcessOutcome(argv, 0, "", "")

    monkeypatch.setattr(shell_module, "run_attached", fake_attached)
    result = shell_operation(root, "human", interactive=True)
    assert result["interactive"] is True
    assert observed[0][0] == "nu"


def test_agent_launch_propagates_external_failure(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    root = tmp_path / "project"
    config_root = root / "shell" / "agent"
    config_root.mkdir(parents=True)
    (config_root / "config.nu").write_text("$env.TEST = true\n", encoding="utf-8")
    (config_root / "env.nu").write_text("$env.TEST_MODE = 'yes'\n", encoding="utf-8")

    def fake_process(*args: object, **kwargs: object) -> ProcessOutcome:
        del args, kwargs
        return ProcessOutcome(("nu",), 3, "", "dependency unavailable")

    monkeypatch.setattr(shell_module, "run_process", fake_process)
    with pytest.raises(KernformProcessError, match="status 3: dependency unavailable"):
        shell_operation(root, "agent")


@pytest.mark.full
def test_nushell_contract_or_explicit_host_skip() -> None:
    if shutil.which("nu") is None:
        pytest.skip("Nushell is unavailable on this host; argv/config contracts remain covered")
    for mode in ("human", "agent"):
        assert shell_operation(ROOT, mode)["exit_code"] == 0
