"""Typed public operations over the private native adapter."""

from example_api_web import _native


def native_version() -> str:
    """Return the native package version."""
    return _native.native_version()


def add(left: int, right: int) -> int:
    """Execute one representative native operation."""
    return _native.add(left, right)
