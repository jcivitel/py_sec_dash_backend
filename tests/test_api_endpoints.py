"""End-to-End-Tests der HTTP-Endpunkte gegen eine echte Redis-Instanz.

Die Router werden in eine minimale App gehängt - ohne den CrowdSec-Listener,
der in der Testumgebung ohnehin keine Gegenstelle hätte.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import alerts, country, health, stats
from app.config import settings
from app.redis_client import HOUR, get_redis_client


@pytest.fixture()
def api() -> TestClient:
    redis_client = get_redis_client()
    if redis_client.redis_client is None:
        pytest.skip("Keine Redis-Instanz erreichbar")
    redis_client.redis_client.flushdb()

    app = FastAPI()
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(alerts.router, prefix="/api/v1")
    app.include_router(country.router, prefix="/api/v1")
    app.include_router(stats.router, prefix="/api/v1")
    return TestClient(app)


def seed(country_code: str, decision_id: str, seconds_ago: float = 0.0) -> None:
    moment = datetime.now(settings.tz) - timedelta(seconds=seconds_ago)
    get_redis_client().add_decision(
        {
            "latitude": 48.85,
            "longitude": 2.35,
            "cn": country_code,
            "timestamp": moment.isoformat(),
        },
        decision_id,
    )


def test_health(api: TestClient):
    assert api.get("/api/v1/health").json()["status"] == "healthy"
    assert api.get("/api/v1/health/redis").json()["redis"] == "connected"


def test_decisions_shape_matches_the_frontend_contract(api: TestClient):
    seed("FR", "7")

    body = api.get("/api/v1/decisions").json()

    assert body["status"] == "success"
    assert len(body["decision"]) == 1
    entry = body["decision"][0]
    assert list(entry) == ["7"]
    assert set(entry["7"]) == {"latitude", "longitude", "cn", "timestamp"}


def test_country_endpoint(api: TestClient):
    seed("FR", "1")
    seed("FR", "2", seconds_ago=2 * HOUR)
    seed("BR", "3")

    body = api.get("/api/v1/country").json()

    assert body["countries"] == [{"FR": 2}, {"BR": 1}]
    assert body["metadata"]["total_attacks"] == 3
    assert body["metadata"]["unique_countries"] == 2


def test_history_pagination_reports_the_true_total(api: TestClient):
    for index in range(3):
        seed("FR", f"h{index}", seconds_ago=index * 60)

    body = api.get("/api/v1/decisions/history?limit=2&offset=0").json()

    assert body["pagination"] == {
        "limit": 2,
        "offset": 0,
        "total": 3,
        "returned": 2,
    }


def test_history_rejects_a_limit_above_the_supported_maximum(api: TestClient):
    # Frühere Fassung meldete le=20000, lieferte aber nie mehr als 1000.
    assert api.get("/api/v1/decisions/history?limit=1000").status_code == 200
    assert api.get("/api/v1/decisions/history?limit=1001").status_code == 422


def test_timeline_endpoint(api: TestClient):
    seed("FR", "1")
    seed("FR", "2", seconds_ago=4 * HOUR)

    body = api.get("/api/v1/timeline").json()

    assert body["status"] == "success"
    assert len(body["timeline"]) == 24
    assert body["total"] == 2
    by_hours_ago = {e["hours_ago"]: e["count"] for e in body["timeline"]}
    assert by_hours_ago[0] == 1
    assert by_hours_ago[4] == 1


# ------------------------------------------------------- Fehlerbehandlung


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/decisions",
        "/api/v1/decisions/history",
        "/api/v1/country",
        "/api/v1/timeline",
    ],
)
def test_errors_do_not_leak_internals(api: TestClient, monkeypatch, path: str, caplog):
    """Ausnahmen dürfen nicht im Klartext an den Aufrufer gehen.

    CodeQL "Information exposure through an exception" - die Antwort trug
    früher `str(e)` und damit Interna nach außen.
    """
    secret = "redis://user:hunter2@internal-host:6379 kaputt"

    def boom():
        raise RuntimeError(secret)

    for module in (alerts, country, stats):
        monkeypatch.setattr(module, "get_redis_client", boom)

    body = api.get(path).json()

    assert body["status"] == "error"
    assert secret not in body["message"]
    assert "hunter2" not in body["message"]
    # Für die Fehlersuche muss der Grund aber im Log stehen.
    assert secret in caplog.text
