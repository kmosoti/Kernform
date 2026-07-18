"""Access to the frozen built-in offline version catalog."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import cast

from kernform.models import VersionCatalog


def load_builtin_catalog() -> VersionCatalog:
    """Load the exact catalog shipped in the installed wheel."""
    raw: object = json.loads(
        files("kernform.data").joinpath("stable-v1.json").read_text(encoding="utf-8")
    )
    if not isinstance(raw, dict):
        raise ValueError("built-in catalog is not an object")
    catalog = cast(dict[str, object], raw).get("catalog")
    if not isinstance(catalog, dict):
        raise ValueError("built-in catalog has no catalog object")
    values = cast(dict[str, object], catalog)
    versions = _string_map(values.get("versions"), "versions")
    images = _string_map(values.get("images"), "images")
    return VersionCatalog(
        id=_string(values.get("id"), "id"),
        hash=_string(values.get("hash"), "hash"),
        resolved_at=_string(values.get("resolved_at"), "resolved_at"),
        source=_string(values.get("source"), "source"),
        versions=versions,
        images=images,
    )


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"built-in catalog {field} is not a string")
    return value


def _string_map(value: object, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"built-in catalog {field} is not an object")
    result: dict[str, str] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(f"built-in catalog {field} contains a non-string entry")
        result[key] = item
    return result
