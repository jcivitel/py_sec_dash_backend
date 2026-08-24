"""Integrationstests für den Redis-Layer.

Laufen gegen eine echte Redis-Instanz. Adresse über ``REDIS_HOST`` /
``REDIS_PORT`` / ``REDIS_DB`` setzen, zum Beispiel::

    docker run -d --rm -p 63790:6379 redis:8-alpine
    REDIS_HOST=localhost REDIS_PORT=63790 REDIS_DB=15 pytest tests/

Die verwendete Datenbank wird vor jedem Test geleert - deshalb bitte eine
eigene DB-Nummer nutzen, nicht die produktive.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.redis_client import (
    ATTACKS_KEY,
    COUNTRIES_CACHE_KEY,
    HOUR,
    LIVE_WINDOW,
    RedisClient,
    _countries_key,
    _hour_of,
    _payload_key,
    _total_key,
)


@pytest.fixture()
def client() -> RedisClient:
    instance = RedisClient()
    if instance.redis_client is None:
        pytest.skip("Keine Redis-Instanz erreichbar")
    instance.redis_client.flushdb()
    return instance


def attack(country: str, *, seconds_ago: float = 0.0) -> dict:
    """Baut eine Decision mit einem Zeitstempel relativ zu jetzt."""
    moment = datetime.now(settings.tz) - timedelta(seconds=seconds_ago)
    return {
        "latitude": 52.52,
        "longitude": 13.405,
        "cn": country,
        "timestamp": moment.isoformat(),
    }


# ---------------------------------------------------------------- Schreibpfad


def test_add_decision_writes_index_payload_and_buckets(client: RedisClient):
    assert client.add_decision(attack("DE"), "1001") is True

    raw = client.redis_client
    hour = _hour_of(time.time())

    assert raw.zscore(ATTACKS_KEY, "1001") is not None
    assert raw.get(_payload_key("1001")) is not None
    # Nutzdaten laufen von allein ab, es bleibt nichts liegen.
    assert 0 < raw.ttl(_payload_key("1001")) <= 24 * HOUR
    assert raw.zscore(_countries_key(hour), "DE") == 1
    assert raw.get(_total_key(hour)) == "1"


def test_hour_buckets_expire_on_a_fixed_schedule(client: RedisClient):
    """Wiederholte Schreibvorgänge dürfen die TTL nicht immer weiter schieben."""
    raw = client.redis_client
    hour = _hour_of(time.time())

    client.add_decision(attack("DE"), "1")
    first_ttl = raw.ttl(_countries_key(hour))
    time.sleep(1.1)
    client.add_decision(attack("DE"), "2")
    second_ttl = raw.ttl(_countries_key(hour))

    assert second_ttl < first_ttl


def test_country_code_is_normalised(client: RedisClient):
    client.add_decision(attack("de"), "1")
    client.add_decision(attack("DE"), "2")

    assert client.get_country_counts_24h() == {"DE": 2}


def test_missing_country_falls_back(client: RedisClient):
    payload = attack("", seconds_ago=0)
    client.add_decision(payload, "1")

    assert client.get_country_counts_24h() == {"UNKNOWN": 1}


# ------------------------------------------------------------- Einzelabfragen


def test_latest_decisions_only_returns_the_live_window(client: RedisClient):
    client.add_decision(attack("DE", seconds_ago=1), "fresh")
    client.add_decision(attack("US", seconds_ago=LIVE_WINDOW + 30), "stale")

    latest = client.get_latest_decisions()
    ids = [next(iter(item)) for item in latest]

    assert ids == ["fresh"]


def test_latest_decisions_are_newest_first(client: RedisClient):
    client.add_decision(attack("DE", seconds_ago=9), "old")
    client.add_decision(attack("US", seconds_ago=5), "mid")
    client.add_decision(attack("FR", seconds_ago=1), "new")

    ids = [next(iter(item)) for item in client.get_latest_decisions()]

    assert ids == ["new", "mid", "old"]


def test_history_paginates_newest_first(client: RedisClient):
    for index in range(5):
        client.add_decision(attack("DE", seconds_ago=index * 60), f"a{index}")

    first_page = client.get_decision_history(limit=2, offset=0)
    second_page = client.get_decision_history(limit=2, offset=2)

    assert [next(iter(i)) for i in first_page] == ["a0", "a1"]
    assert [next(iter(i)) for i in second_page] == ["a2", "a3"]
    assert client.get_history_count() == 5


def test_history_limit_is_clamped(client: RedisClient):
    client.add_decision(attack("DE"), "1")

    # Übergroße Werte dürfen nicht durchschlagen, sondern werden gedeckelt.
    assert len(client.get_decision_history(limit=99_999)) == 1


def test_payload_returns_the_stored_fields(client: RedisClient):
    payload = attack("BR")
    client.add_decision(payload, "42")

    entry = client.get_decision_history(limit=1)[0]["42"]

    assert entry["cn"] == "BR"
    assert entry["latitude"] == payload["latitude"]
    assert entry["timestamp"] == payload["timestamp"]


def test_orphaned_index_entries_are_dropped(client: RedisClient):
    """Läuft eine Nutzdaten-TTL ab, verschwindet auch der Index-Eintrag."""
    client.add_decision(attack("DE"), "ghost")
    client.redis_client.delete(_payload_key("ghost"))

    assert client.get_decision_history(limit=10) == []
    assert client.redis_client.zscore(ATTACKS_KEY, "ghost") is None


# ------------------------------------------------------------------ Aggregate


def test_country_stats_aggregate_across_hours(client: RedisClient):
    client.add_decision(attack("US", seconds_ago=30), "1")
    client.add_decision(attack("US", seconds_ago=2 * HOUR), "2")
    client.add_decision(attack("US", seconds_ago=5 * HOUR), "3")
    client.add_decision(attack("CN", seconds_ago=3 * HOUR), "4")

    result = client.get_decisions_by_country()

    assert result["status"] == "success"
    assert result["countries"] == [{"US": 3}, {"CN": 1}]
    assert result["metadata"]["total_attacks"] == 4
    assert result["metadata"]["unique_countries"] == 2


def test_attacks_per_hour_is_the_last_hour_not_the_daily_average(client: RedisClient):
    client.add_decision(attack("US", seconds_ago=60), "1")
    client.add_decision(attack("US", seconds_ago=120), "2")
    client.add_decision(attack("US", seconds_ago=6 * HOUR), "3")

    metadata = client.get_decisions_by_country()["metadata"]

    assert metadata["attacks_per_hour"] == 2
    assert metadata["total_attacks"] == 3


def test_attacks_outside_the_window_are_ignored(client: RedisClient):
    client.add_decision(attack("US", seconds_ago=30), "recent")
    client.add_decision(attack("RU", seconds_ago=30 * HOUR), "ancient")

    assert client.get_total_attacks_24h() == 1


def test_country_union_is_cached_briefly(client: RedisClient):
    client.add_decision(attack("US"), "1")
    client.get_country_counts_24h()

    ttl = client.redis_client.ttl(COUNTRIES_CACHE_KEY)

    assert 0 < ttl <= 15


# ------------------------------------------------------------------- Timeline


def test_timeline_has_one_entry_per_hour(client: RedisClient):
    timeline = client.get_timeline_24h()

    assert len(timeline) == 24
    assert [entry["hours_ago"] for entry in timeline] == list(range(23, -1, -1))
    assert all(entry["count"] == 0 for entry in timeline)


def test_timeline_counts_land_in_the_right_hour(client: RedisClient):
    client.add_decision(attack("DE", seconds_ago=30), "now1")
    client.add_decision(attack("DE", seconds_ago=30), "now2")
    client.add_decision(attack("US", seconds_ago=3 * HOUR), "older")

    by_hours_ago = {entry["hours_ago"]: entry["count"] for entry in client.get_timeline_24h()}

    assert by_hours_ago[0] == 2
    assert by_hours_ago[3] == 1
    assert sum(by_hours_ago.values()) == 3


# -------------------------------------------------------------------- Wartung


def test_clear_all_removes_everything(client: RedisClient):
    client.add_decision(attack("DE"), "1")
    client.get_country_counts_24h()

    assert client.clear_all() is True

    assert client.get_history_count() == 0
    assert client.get_country_counts_24h() == {}
    assert client.redis_client.keys("sec:*") == []
