from __future__ import annotations

import json
import signal
import subprocess
import sys
from pathlib import Path

from {{ module_name }}.daemon import DaemonRuntime


def test_daemon_once_writes_terminal_status(tmp_path: Path) -> None:
    status_file = tmp_path / "status.json"
    runtime = DaemonRuntime(status_file)
    assert runtime.run(0.01, once=True) == 0
    assert json.loads(status_file.read_text(encoding="utf-8"))["state"] == "stopped"


def test_daemon_process_stops_on_sigterm(tmp_path: Path) -> None:
    status_file = tmp_path / "status.json"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "{{ module_name }}.daemon",
            "--heartbeat-seconds",
            "0.01",
            "--status-file",
            str(status_file),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(100):
            if status_file.is_file():
                break
            import time

            time.sleep(0.01)
        assert status_file.is_file()
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == 0, stderr
    records = [json.loads(line) for line in stdout.splitlines()]
    assert records[0]["state"] == "running"
    assert records[-1] == json.loads(status_file.read_text(encoding="utf-8"))
    assert records[-1]["state"] == "stopped"
    assert records[-1]["reason"] == "sigterm"
