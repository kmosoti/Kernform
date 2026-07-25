from litestar.testing import TestClient

from {{ module_name }}.app import app, bind_host


def test_health_and_native_routes() -> None:
    with TestClient(app=app) as client:
        assert client.get("/health").json() == {"status": "ok", "version": "0.1.0"}
        assert client.get("/native").json() == {"result": 42}


def test_exposure_policy() -> None:
    assert bind_host("embedded") == ""
    assert bind_host("local") == "127.0.0.1"
    assert bind_host("network") == "0.0.0.0"
