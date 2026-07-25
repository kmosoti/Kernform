"""Command-line interface for {{ project_name }}."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from {{ module_name }} import add


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="{{ project_name }}")
    parser.add_argument("left", type=int, nargs="?")
    parser.add_argument("right", type=int, nargs="?")
    parser.add_argument("--format", choices=["human", "json", "nuon"], default="human")
    parser.add_argument("--agent", action="store_true")
    parser.add_argument("--completion", choices=["bash", "nushell"])
    args = parser.parse_args(argv)
    if args.completion:
        print(_completion(args.completion))
        return 0
    if args.left is None or args.right is None:
        parser.error("left and right are required unless --completion is used")
    value = add(args.left, args.right)
    if args.agent or args.format in {"json", "nuon"}:
        print(json.dumps({"result": value}, sort_keys=True, separators=(",", ":")))
    else:
        print(value)
    return 0


def _completion(shell: str) -> str:
    if shell == "bash":
        return 'complete -W "--format --agent --completion" {{ project_name }}'
    return (
        'export extern "{{ project_name }}" ['
        "left: int, right: int, --format: string, --agent, --completion: string]"
    )


if __name__ == "__main__":
    raise SystemExit(main())
