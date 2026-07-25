from __future__ import annotations

from pathlib import Path

import kernform
from kernform.cli import build_parser, dispatch
from kernform.versioning import inspect_version_state, plan_version_update

ROOT = Path(__file__).resolve().parents[2]


def test_source_repository_exact_version_state_is_conformant() -> None:
    state = inspect_version_state(ROOT)
    assert state["conformant"] is True
    assert state["differences"] == []


def test_generated_project_has_exact_frozen_locks_and_zero_update_plan(tmp_path: Path) -> None:
    root = tmp_path / "example"
    kernform.initialize_project(
        kernform.InitRequest(
            name="example",
            destination=root,
            git=kernform.GitOptions(enabled=False),
        )
    )
    assert inspect_version_state(root)["conformant"] is True
    assert plan_version_update(root).operation_count == 0


def test_version_update_is_explicit_and_repairs_generated_catalog_drift(tmp_path: Path) -> None:
    root = tmp_path / "example"
    kernform.initialize_project(
        kernform.InitRequest(
            name="example",
            destination=root,
            git=kernform.GitOptions(enabled=False),
        )
    )
    lock = root / ".kernform/toolchains.lock.toml"
    lock.write_text(lock.read_text().replace('catalog_hash = "', 'catalog_hash = "bad'))
    assert inspect_version_state(root)["conformant"] is False

    parser = build_parser()
    refused = dispatch(parser.parse_args(["versions", "update", "--path", str(root)]))
    assert refused.status == "refused"
    applied = dispatch(parser.parse_args(["versions", "update", "--path", str(root), "--accept"]))
    assert applied.status == "success"
    assert inspect_version_state(root)["conformant"] is True
