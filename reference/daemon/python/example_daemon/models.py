"""Typed public models."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Calculation:
    """One native addition request."""

    left: int
    right: int
