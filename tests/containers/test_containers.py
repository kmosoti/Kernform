from __future__ import annotations

import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

import kernform.container as container_module
from kernform.container import (
    ContainerContext,
    container_context,
    container_operation,
    inspect_podman,
)
from kernform.process import ProcessOutcome, run_checked, run_process

ROOT = Path(__file__).resolve().parents[2]


def _containerfile(root: Path) -> str:
    return (root / "containers/Containerfile").read_text(encoding="utf-8")


def test_container_assets_pin_images_and_reduce_runtime_privilege(tmp_path: Path) -> None:
    destination = tmp_path / "example"
    import kernform

    kernform.initialize_project(
        kernform.InitRequest(
            name="example",
            destination=destination,
            git=kernform.GitOptions(enabled=False),
        )
    )
    content = _containerfile(destination)
    assert "python:3.14.6-slim@sha256:" in content
    assert "rust:1.96.0-slim@sha256:" in content
    assert "USER 65532:65532" in content
    assert "USER root" not in content
    compose = (destination / "containers/compose.dev.yaml").read_text(encoding="utf-8")
    quadlet = (destination / "containers/quadlet/example.container").read_text(encoding="utf-8")
    assert "read_only: true" in compose
    assert 'cap_drop: ["ALL"]' in compose
    assert 'security_opt: ["no-new-privileges"]' in compose
    assert "ReadOnly=true" in quadlet
    assert "NoNewPrivileges=true" in quadlet
    assert "DropCapability=all" in quadlet


def test_worktree_names_are_stable_and_path_isolated(tmp_path: Path) -> None:
    first = tmp_path / "first/example"
    second = tmp_path / "second/example"
    for root in (first, second):
        (root / "containers").mkdir(parents=True)
        (root / "containers/Containerfile").write_text("FROM scratch\n", encoding="utf-8")
    first_context = container_context(first)
    assert first_context == container_context(first)
    assert first_context.project == "example"
    assert first_context.worktree_hash != container_context(second).worktree_hash


@pytest.mark.full
def test_host_podman_is_rootless() -> None:
    result = inspect_podman(ROOT)
    assert result["rootless"] is True
    assert result["worktree_hash"] == container_context(ROOT).worktree_hash


def test_container_run_uses_only_structured_security_arguments(monkeypatch: MonkeyPatch) -> None:
    observed: list[tuple[str, ...]] = []

    def fake_inspect(_root: Path) -> dict[str, object]:
        return {"rootless": True}

    def fake_build(_context: ContainerContext, _target: str, _image: str) -> ProcessOutcome:
        return ProcessOutcome(("podman", "build"), 0, "", "")

    monkeypatch.setattr(container_module, "inspect_podman", fake_inspect)
    monkeypatch.setattr(container_module, "_build", fake_build)

    def fake_checked(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: int,
        environment: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> ProcessOutcome:
        del cwd, timeout_seconds, environment, input_text
        observed.append(argv)
        return ProcessOutcome(argv, 0, "container-id\n", "")

    monkeypatch.setattr(container_module, "run_checked", fake_checked)
    result = container_operation(ROOT, "run")
    assert result["action"] == "run"
    argv = observed[-1]
    assert argv[:2] == ("podman", "run")
    assert "--read-only" in argv
    assert argv[argv.index("--cap-drop") : argv.index("--cap-drop") + 2] == (
        "--cap-drop",
        "all",
    )
    assert "no-new-privileges" in argv
    assert not any(value in {"sh", "bash", "-c"} for value in argv)


def test_podman_info_shape_is_json() -> None:
    # The live boundary evidence must also remain serializable.
    assert json.dumps(inspect_podman(ROOT), sort_keys=True)


@pytest.mark.full
@pytest.mark.container
@pytest.mark.parametrize(
    ("signature", "web"),
    [
        ("sdk", False),
        ("cli", False),
        ("api", False),
        ("interactive-web", True),
        ("daemon", False),
    ],
    ids=["sdk", "cli", "api", "interactive-web", "daemon"],
)
def test_generated_signature_container_matrix(tmp_path: Path, signature: str, web: bool) -> None:
    if os.environ.get("KERNFORM_CONTAINER_SMOKE") != "1":
        pytest.skip("container matrix is run explicitly by the maintained full tier")
    if shutil.which("podman") is None:
        pytest.skip("Podman is unavailable on this host")

    import kernform

    name = f"container-{signature}"
    root = tmp_path / name
    kernform.initialize_project(
        kernform.InitRequest(
            name=name,
            destination=root,
            signatures=(kernform.Signature(signature),),
            git=kernform.GitOptions(enabled=False),
        )
    )
    context = container_context(root)
    try:
        assert container_operation(root, "test")["action"] == "test"
        assert container_operation(root, "build")["action"] == "build"
        runtime_probe = run_checked(
            (
                "podman",
                "run",
                "--rm",
                "--read-only",
                "--entrypoint",
                "python",
                context.image,
                "-c",
                (
                    "import pathlib,shutil;"
                    "assert shutil.which('cargo') is None;"
                    "assert shutil.which('maturin') is None;"
                    "assert shutil.which('nu') is None;"
                    "assert not pathlib.Path('/workspace').exists()"
                ),
            ),
            cwd=root,
            timeout_seconds=120,
        )
        assert runtime_probe.exit_code == 0
        if signature in {"api", "interactive-web"}:
            container_operation(root, "run")
            _wait_for_health(context.host_port, expect_web=web)
    finally:
        _cleanup_signature_containers(context)


def _wait_for_health(port: int, *, expect_web: bool) -> None:
    deadline = time.monotonic() + 30
    health = f"http://127.0.0.1:{port}/health"
    while True:
        try:
            with urllib.request.urlopen(health, timeout=2) as response:
                document = json.loads(response.read())
            assert document["status"] == "ok"
            break
        except OSError, urllib.error.URLError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
    if expect_web:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            html = response.read().decode().lower()
        assert "<main" in html
        assert "<script" not in html


def _cleanup_signature_containers(context: ContainerContext) -> None:
    for name in (context.runtime_name, context.development_name, context.test_name):
        run_process(
            ("podman", "rm", "--force", "--ignore", name),
            cwd=context.root,
            timeout_seconds=60,
        )
    run_process(
        ("podman", "network", "rm", "--force", context.network_name),
        cwd=context.root,
        timeout_seconds=60,
    )
    run_process(
        ("podman", "volume", "rm", "--force", context.cache_volume_name),
        cwd=context.root,
        timeout_seconds=60,
    )
