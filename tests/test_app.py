from fastapi.testclient import TestClient

from ranobelib_epub.app import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index() -> None:
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "RanobeLib EPUB Builder" in response.text
