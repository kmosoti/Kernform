from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

import pytest

import kernform
from kernform.errors import KernformPolicyError


def test_profile_plan_is_deterministic_and_has_safe_destinations() -> None:
    first = kernform.plan_project(name="example", profile=kernform.Profile.LIBRARY)
    second = kernform.plan_project(name="example", profile=kernform.Profile.LIBRARY)
    assert first.json == second.json
    operations_value = first.document["operations"]
    assert isinstance(operations_value, list)
    operations = cast(list[object], operations_value)
    paths: list[str] = []
    for operation_value in operations:
        if not isinstance(operation_value, dict):
            continue
        operation = cast(dict[str, object], operation_value)
        path = operation.get("path")
        if isinstance(path, str):
            paths.append(path)
    assert all("../" not in path for path in paths)
    assert '"program":"sh"' not in first.json
    assert '"program":"bash"' not in first.json


def test_unknown_capability_is_refused_before_mutation() -> None:
    with pytest.raises(KernformPolicyError, match="unknown capability"):
        kernform.plan_project(
            name="example",
            profile=kernform.Profile.LIBRARY,
            capabilities=("unknown",),
        )


def test_second_initialization_is_zero_operation_and_git_stable(tmp_path: Path) -> None:
    destination = tmp_path / "example"
    request = kernform.InitRequest(name="example", destination=destination)
    first = kernform.initialize_project(request)
    assert first.operation_count > 0
    before = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    second = kernform.initialize_project(request)
    after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert second.operation_count == 0
    assert after == before


def test_api_web_output_has_no_javascript_or_node_artifacts(tmp_path: Path) -> None:
    destination = tmp_path / "api-web"
    kernform.initialize_project(
        kernform.InitRequest(
            name="api-web",
            destination=destination,
            profile=kernform.Profile.API,
            capabilities=("web-server",),
            git=kernform.GitOptions(enabled=False),
        )
    )
    paths = {path.name.lower() for path in destination.rglob("*") if path.is_file()}
    assert "package.json" not in paths
    assert not any(path.endswith((".js", ".mjs", ".cjs")) for path in paths)
    html = (destination / "python/api_web/templates/index.html").read_text().lower()
    assert "<script" not in html
    assert "onclick=" not in html


def test_module_scaffold_is_seeded_idempotent_and_preserves_user_edits(tmp_path: Path) -> None:
    destination = tmp_path / "example"
    kernform.initialize_project(kernform.InitRequest(name="example", destination=destination))

    from kernform.scaffold import scaffold_module

    first = scaffold_module(destination, "module", "billing")
    module = destination / "python/example/billing.py"
    assert first.operation_count > 0
    assert module.is_file()
    second = scaffold_module(destination, "module", "billing")
    assert second.operation_count == 0

    module.write_text("# user-owned change\n", encoding="utf-8")
    with pytest.raises(KernformPolicyError, match="error diagnostics"):
        scaffold_module(destination, "module", "billing")
    assert module.read_text(encoding="utf-8") == "# user-owned change\n"


def test_modified_managed_file_conflicts_before_regeneration(tmp_path: Path) -> None:
    destination = tmp_path / "example"
    request = kernform.InitRequest(name="example", destination=destination)
    kernform.initialize_project(request)
    managed = destination / "pyproject.toml"
    changed = managed.read_text(encoding="utf-8") + "\n# user-managed extension\n"
    managed.write_text(changed, encoding="utf-8")

    with pytest.raises(KernformPolicyError, match="error diagnostics"):
        kernform.initialize_project(request)
    assert managed.read_text(encoding="utf-8") == changed
