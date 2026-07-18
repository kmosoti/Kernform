"""Clean-environment wheel import verification used by the full tier."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from kernform.process import run_checked


def main() -> int:
    """Install the single built wheel into an isolated environment and import it."""
    root = Path.cwd().resolve(strict=True)
    wheels = sorted((root / "target/kernform-test/wheels").glob("kernform-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one Kernform wheel, found {len(wheels)}")
    with tempfile.TemporaryDirectory(prefix="kernform-wheel-") as raw:
        environment = Path(raw) / ".venv"
        run_checked(
            ("uv", "venv", "--python", "3.14", str(environment)),
            cwd=root,
            timeout_seconds=120,
        )
        python = environment / "bin/python"
        run_checked(
            ("uv", "pip", "install", "--python", str(python), str(wheels[0])),
            cwd=root,
            timeout_seconds=300,
        )
        result = run_checked(
            (
                str(python),
                "-c",
                "import json, kernform; print(json.dumps({'version': kernform.version()}))",
            ),
            cwd=root,
            timeout_seconds=30,
        )
    document: object = json.loads(result.stdout)
    print(json.dumps({"schema": "kernform.wheel-check/v1", "result": document}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
