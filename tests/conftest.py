import pytest
from fastapi.testclient import TestClient

from worker.api import create_app
from worker.config import Settings

WORKER = {"Authorization": "Bearer local-worker"}
REVIEWER = {"Authorization": "Bearer local-reviewer"}


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(db_path=str(tmp_path / "test.sqlite3"), enable_faults=True, retry_delay=0))


@pytest.fixture
def client(app):
    with TestClient(app, headers=WORKER) as test_client:
        yield test_client


def run(client, vendor="Acme Supplies"):
    response = client.post("/api/tasks", json={"goal": f"Record the latest invoice from {vendor}."})
    assert response.status_code == 201, response.text
    return response.json()


def fault(client, name, count=1):
    response = client.post("/api/faults", json={"name": name, "count": count}, headers=REVIEWER)
    assert response.status_code == 200
