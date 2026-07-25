from litestar.testing import TestClient

from {{ module_name }}.web import app


def test_server_rendered_page_has_no_script() -> None:
    with TestClient(app=app) as client:
        response = client.get("/")
        assert response.status_code == 200
        lower = response.text.lower()
        assert "<main" in lower
        assert "<script" not in lower
        assert "onclick=" not in lower
