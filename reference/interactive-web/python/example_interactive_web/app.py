"""Typed Litestar application using only the public service boundary."""

from typing import Literal

import msgspec
from litestar import Litestar, get

from example_interactive_web import add, native_version

Exposure = Literal["embedded", "local", "network"]


class Health(msgspec.Struct, frozen=True):
    status: str
    version: str


@get("/health")
async def health() -> Health:
    return Health(status="ok", version=native_version())


@get("/native")
async def native_operation() -> dict[str, int]:
    return {"result": add(20, 22)}


def bind_host(exposure: Exposure) -> str:
    if exposure == "embedded":
        return ""
    if exposure == "local":
        return "127.0.0.1"
    return "0.0.0.0"


app = Litestar(route_handlers=[health, native_operation])
