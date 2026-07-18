from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import kernform
from kernform.errors import KernformPolicyError, KernformPreconditionError

ROOT = Path(__file__).resolve().parents[2]


def catalog() -> kernform.VersionCatalog:
    raw = json.loads((ROOT / "fixtures/catalogs/stable-v1.json").read_text())
    document = raw["catalog"]
    return kernform.VersionCatalog(
        id=document["id"],
        hash=document["hash"],
        resolved_at=document["resolved_at"],
        source=document["source"],
        versions=document["versions"],
        images=document["images"],
    )


def request() -> kernform.PlanRequest:
    return kernform.PlanRequest(
        name="example",
        profile=kernform.Profile.LIBRARY,
        capabilities=("python-package",),
        git=kernform.GitOptions(enabled=False),
        snapshot=kernform.RepositorySnapshot.empty(),
        catalog=catalog(),
        files=(
            kernform.RenderedFile(
                path="README.md",
                content="# Example\n",
                ownership=kernform.Ownership.SEEDED,
            ),
        ),
    )


def test_public_api_plans_and_applies_without_importing_native(tmp_path: Path) -> None:
    plan = kernform.plan_initialization(request())
    destination = tmp_path / "example"
    result = kernform.apply_plan(kernform.ApplyRequest(destination, plan, new_project=True))
    assert result.plan_id == plan.plan_id
    assert result.operation_count == plan.operation_count
    assert (destination / "README.md").read_text() == "# Example\n"
    assert (destination / ".kernform/state.json").is_file()


def test_native_core_error_identity_is_preserved() -> None:
    invalid = request()
    invalid = kernform.PlanRequest(
        name="Invalid Name",
        profile=invalid.profile,
        capabilities=invalid.capabilities,
        git=invalid.git,
        snapshot=invalid.snapshot,
        catalog=invalid.catalog,
        files=invalid.files,
    )
    with pytest.raises(KernformPolicyError, match="core:invalid_intent"):
        kernform.plan_initialization(invalid)


def test_apply_precondition_error_has_stable_public_type(tmp_path: Path) -> None:
    plan = kernform.plan_initialization(request())
    destination = tmp_path / "example"
    destination.mkdir()
    with pytest.raises(KernformPreconditionError, match="engine:precondition"):
        kernform.apply_plan(kernform.ApplyRequest(destination, plan, new_project=True))


def test_snapshot_round_trip(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("value\n")
    snapshot = kernform.inspect_repository(tmp_path)
    assert snapshot.exists
    assert snapshot.files["file.txt"].ownership is kernform.Ownership.USER


def test_snapshot_reports_the_actual_unborn_git_branch(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init", "--initial-branch=feature/preserved"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    snapshot = kernform.inspect_repository(tmp_path)
    assert snapshot.git
    assert snapshot.primary_branch == "feature/preserved"
