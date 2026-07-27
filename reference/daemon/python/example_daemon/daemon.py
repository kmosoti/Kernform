"""Signal-aware standard-library daemon lifecycle."""

from __future__ import annotations

import argparse
import json
import signal
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Sequence


@dataclass(frozen=True, slots=True)
class DaemonStatus:
    """Machine-readable daemon lifecycle status."""

    state: str
    pid: int
    occurred_at: str
    reason: str | None = None


class DaemonRuntime:
    """Bounded lifecycle controlled by process signals or an explicit stop."""

    def __init__(self, status_file: Path | None = None) -> None:
        import os

        self._pid = os.getpid()
        self._status_file = status_file
        self._stop = threading.Event()
        self._reason: str | None = None

    def request_stop(self, reason: str) -> None:
        """Request an orderly shutdown."""
        self._reason = reason
        self._stop.set()

    def handle_signal(self, signum: int, _frame: FrameType | None) -> None:
        """Translate a process signal into an orderly stop request."""
        self.request_stop(signal.Signals(signum).name.lower())

    def run(self, heartbeat_seconds: float, *, once: bool = False) -> int:
        """Run until stopped, emitting structured lifecycle records."""
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        self._emit("running")
        if once:
            self.request_stop("once")
        while not self._stop.wait(heartbeat_seconds):
            self._emit("running", "heartbeat")
        self._emit("stopped", self._reason)
        return 0

    def _emit(self, state: str, reason: str | None = None) -> None:
        status = DaemonStatus(
            state=state,
            pid=self._pid,
            occurred_at=datetime.now(UTC).isoformat(),
            reason=reason,
        )
        content = json.dumps(asdict(status), sort_keys=True, separators=(",", ":"))
        print(content, flush=True)
        if self._status_file is not None:
            temporary = self._status_file.with_suffix(self._status_file.suffix + ".tmp")
            temporary.write_text(f"{content}\n", encoding="utf-8")
            temporary.replace(self._status_file)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the daemon lifecycle entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args(argv)
    runtime = DaemonRuntime(arguments.status_file)
    signal.signal(signal.SIGINT, runtime.handle_signal)
    signal.signal(signal.SIGTERM, runtime.handle_signal)
    return runtime.run(arguments.heartbeat_seconds, once=arguments.once)


if __name__ == "__main__":
    raise SystemExit(main())
