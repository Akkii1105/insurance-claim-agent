"""Smoke tests to verify the application starts correctly."""


def test_health_check(client):
    """Verify the health endpoint returns 200 with expected payload."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"


def test_docs_accessible(client):
    """Verify Swagger docs are accessible (useful for hackathon demo)."""
    response = client.get("/docs")
    assert response.status_code == 200
