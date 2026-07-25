"""Server-rendered web routes with no browser-side scripting."""

from pathlib import Path

from litestar import Litestar, get
from litestar.response import Response

from example_api_web.app import health, native_operation

ROOT = Path(__file__).resolve().parent


@get("/")
async def index() -> Response[str]:
    return Response(
        content=(ROOT / "templates/index.html").read_text(encoding="utf-8"),
        media_type="text/html",
    )


@get("/static/site.css")
async def stylesheet() -> Response[str]:
    return Response(
        content=(ROOT / "static/site.css").read_text(encoding="utf-8"),
        media_type="text/css",
    )


app = Litestar(route_handlers=[index, stylesheet, health, native_operation])
