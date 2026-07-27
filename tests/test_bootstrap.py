from __future__ import annotations

from pathlib import Path

import kernform

ROOT = Path(__file__).resolve().parents[1]


def test_native_version_matches_distribution() -> None:
    assert kernform.version() == kernform.__version__ == "0.2.0"


def test_canonical_workspace_paths_exist() -> None:
    expected = {
        "capabilities",
        "containers",
        "crates",
        "docs",
        "fixtures",
        "signatures",
        "python",
        "reference",
        "schemas",
        "shell",
        "templates",
    }
    assert expected <= {path.name for path in ROOT.iterdir() if path.is_dir()}
