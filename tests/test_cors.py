from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _preflight(origin: str):
    return client.options(
        "/api/v1/category-classifier/predict",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
        },
    )


def test_cors_allows_vercel_origin():
    response = _preflight("https://prep-fe.vercel.app")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://prep-fe.vercel.app"


def test_cors_allows_localhost_origin():
    response = _preflight("http://localhost:3000")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_allows_configured_production_origin():
    response = _preflight("https://prepwell.shop")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://prepwell.shop"


def test_cors_rejects_other_vercel_origin():
    response = _preflight("https://unknown-preview.vercel.app")

    assert "access-control-allow-origin" not in response.headers
