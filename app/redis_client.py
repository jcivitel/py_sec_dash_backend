"""Redis-Zugriff für CrowdSec-Decisions.

Datenmodell
-----------
Jeder Angriff wird genau einmal gespeichert und verschwindet nach 24 Stunden
von selbst wieder. Aggregate werden nicht aus den Rohdaten berechnet, sondern
beim Schreiben in Stundeneimer fortgeschrieben - dadurch bleibt jede Abfrage
unabhängig von der Menge der gespeicherten Angriffe.

===========================  ======  ==================================================
Key                          Typ     Inhalt
===========================  ======  ==================================================
``sec:attacks``              ZSET    member = Decision-ID, score = Unix-Zeit.
                                     Der Index über alle Angriffe der letzten 24 h.
``sec:attack:{id}``          STRING  JSON-Nutzdaten eines Angriffs, TTL 24 h.
``sec:hour:{h}:countries``   ZSET    member = Ländercode, score = Anzahl in Stunde ``h``.
``sec:hour:{h}:total``       STRING  Gesamtzahl der Angriffe in Stunde ``h``.
``sec:countries:24h``        ZSET    Kurzlebiger Cache der Vereinigung der 24 Eimer.
===========================  ======  ==================================================

``h`` ist die volle Unix-Stunde (``int(timestamp // 3600)``). Die Stundeneimer
laufen per ``EXPIREAT`` 25 Stunden nach Ende ihrer Stunde ab, sodass immer
mindestens die letzten 24 vollständigen Stunden vorliegen.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple

import redis

from app.config import settings

logger = logging.getLogger(__name__)

# --- Zeitfenster -----------------------------------------------------------
HOUR = 3600
WINDOW_HOURS = 24
TTL_24H = WINDOW_HOURS * HOUR
#: Stundeneimer leben eine Stunde länger als das Fenster, damit die laufende
#: Stunde beim Rollover nicht verfrüht wegfällt.
BUCKET_TTL = TTL_24H + HOUR
#: Zeitfenster, in dem ein Angriff als "gerade laufend" gilt (Kartenanzeige).
LIVE_WINDOW = 20

# --- Keys ------------------------------------------------------------------
ATTACKS_KEY = "sec:attacks"
ATTACK_PAYLOAD_PREFIX = "sec:attack:"
HOUR_PREFIX = "sec:hour:"
COUNTRIES_CACHE_KEY = "sec:countries:24h"
#: So lange gilt die zwischengespeicherte Ländervereinigung als frisch.
COUNTRIES_CACHE_TTL = 15

#: Schlüssel aus einer früheren Version, die beim Aufräumen mit entfernt werden.
LEGACY_KEYS = (
    "crowdsec:decisions:hash",
    "crowdsec:decisions:history",
    "crowdsec:attacks:24h",
    "crowdsec:countries:24h",
)

#: Der Index wird höchstens alle 60 s beschnitten - häufiger bringt nichts,
#: weil alle Abfragen ohnehin nach Zeitfenster filtern.
TRIM_INTERVAL = 60


def _hour_of(timestamp: float) -> int:
    """Volle Unix-Stunde, in die ein Zeitstempel fällt."""
    return int(timestamp // HOUR)


def _countries_key(hour: int) -> str:
    return f"{HOUR_PREFIX}{hour}:countries"


def _total_key(hour: int) -> str:
    return f"{HOUR_PREFIX}{hour}:total"


def _payload_key(decision_id: str) -> str:
    return f"{ATTACK_PAYLOAD_PREFIX}{decision_id}"


class RedisClient:
    """Kapselt sämtliche Redis-Zugriffe des Backends."""

    def __init__(self) -> None:
        self._last_trim = 0.0
        self.redis_client: Optional[redis.Redis] = self._connect()

    # ------------------------------------------------------------------
    # Verbindung
    # ------------------------------------------------------------------
    @staticmethod
    def _connect() -> Optional[redis.Redis]:
        try:
            client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password or None,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                # Erkennt stillschweigend abgebrochene Verbindungen und baut sie
                # neu auf, statt dauerhaft ins Leere zu laufen.
                health_check_interval=30,
                retry_on_timeout=True,
            )
            client.ping()
            logger.info("Redis-Verbindung hergestellt")
            return client
        except Exception as exc:
            logger.error("Redis-Verbindung fehlgeschlagen: %s", exc)
            return None

    def _client(self) -> Optional[redis.Redis]:
        """Liefert eine benutzbare Verbindung und versucht bei Bedarf einen Neuaufbau."""
        if self.redis_client is None:
            self.redis_client = self._connect()
        return self.redis_client

    # ------------------------------------------------------------------
    # Schreibpfad
    # ------------------------------------------------------------------
    def add_decision(self, decision_data: Dict[str, Any], decision_id: str) -> bool:
        """Speichert einen Angriff und schreibt die Stundenaggregate fort.

        Alle Schreibvorgänge laufen in einer Pipeline, also in einem einzigen
        Roundtrip zum Server.
        """
        client = self._client()
        if client is None:
            return False

        timestamp = self._timestamp_of(decision_data)
        hour = _hour_of(timestamp)
        country = str(decision_data.get("cn") or "unknown").upper()
        # Festes Ablaufdatum, unabhängig davon, wie oft in die Stunde
        # geschrieben wird.
        expire_at = int((hour + 1) * HOUR + BUCKET_TTL)

        try:
            pipe = client.pipeline(transaction=False)
            pipe.zadd(ATTACKS_KEY, {decision_id: timestamp})
            pipe.set(_payload_key(decision_id), json.dumps(decision_data), ex=TTL_24H)
            pipe.zincrby(_countries_key(hour), 1, country)
            pipe.expireat(_countries_key(hour), expire_at)
            pipe.incr(_total_key(hour))
            pipe.expireat(_total_key(hour), expire_at)
            pipe.execute()
        except Exception as exc:
            logger.error("Angriff %s konnte nicht gespeichert werden: %s", decision_id, exc)
            return False

        self._trim_if_due()
        logger.debug("Angriff %s (%s) gespeichert", decision_id, country)
        return True

    @staticmethod
    def _timestamp_of(decision_data: Dict[str, Any]) -> float:
        """Nutzt den Zeitstempel der Decision, sonst die aktuelle Zeit."""
        raw = decision_data.get("timestamp")
        if raw:
            try:
                return datetime.fromisoformat(str(raw)).timestamp()
            except ValueError:
                logger.debug("Unlesbarer Zeitstempel %r, nutze aktuelle Zeit", raw)
        return time.time()

    def _trim_if_due(self) -> None:
        """Entfernt Index-Einträge, die aus dem 24-h-Fenster gefallen sind.

        Die Nutzdaten laufen über ihre eigene TTL ab; hier wird nur der Index
        aufgeräumt, und das höchstens einmal pro ``TRIM_INTERVAL``.
        """
        now = time.time()
        if now - self._last_trim < TRIM_INTERVAL:
            return
        self._last_trim = now

        client = self._client()
        if client is None:
            return
        try:
            removed = client.zremrangebyscore(ATTACKS_KEY, "-inf", now - TTL_24H)
            if removed:
                logger.debug("%s abgelaufene Angriffe aus dem Index entfernt", removed)
        except Exception as exc:
            logger.error("Index konnte nicht beschnitten werden: %s", exc)

    # ------------------------------------------------------------------
    # Lesepfad: einzelne Angriffe
    # ------------------------------------------------------------------
    def _load_payloads(self, decision_ids: List[str]) -> List[Dict[str, Any]]:
        """Holt die Nutzdaten zu einer ID-Liste in einem einzigen ``MGET``."""
        client = self._client()
        if client is None or not decision_ids:
            return []

        try:
            raw_values = client.mget([_payload_key(i) for i in decision_ids])
        except Exception as exc:
            logger.error("Nutzdaten konnten nicht geladen werden: %s", exc)
            return []

        result: List[Dict[str, Any]] = []
        orphaned: List[str] = []

        for decision_id, raw in zip(decision_ids, raw_values):
            if raw is None:
                # Nutzdaten abgelaufen, Index-Eintrag noch vorhanden.
                orphaned.append(decision_id)
                continue
            try:
                result.append({decision_id: json.loads(raw)})
            except json.JSONDecodeError:
                logger.warning("Angriff %s enthält kein gültiges JSON", decision_id)
                orphaned.append(decision_id)

        if orphaned:
            try:
                client.zrem(ATTACKS_KEY, *orphaned)
            except Exception as exc:
                logger.debug("Verwaiste Index-Einträge blieben stehen: %s", exc)

        return result

    def get_latest_decisions(self, count: int = 20) -> List[Dict[str, Any]]:
        """Angriffe der letzten ``LIVE_WINDOW`` Sekunden, neueste zuerst.

        Jeder Angriff hat sein eigenes Zeitfenster - es fällt also nicht mehr
        die gesamte Anzeige auf einmal weg.
        """
        client = self._client()
        if client is None:
            return []

        now = time.time()
        try:
            ids = client.zrevrangebyscore(
                ATTACKS_KEY,
                "+inf",
                now - LIVE_WINDOW,
                start=0,
                num=max(1, count),
            )
        except Exception as exc:
            logger.error("Aktuelle Angriffe konnten nicht gelesen werden: %s", exc)
            return []

        return self._load_payloads([str(i) for i in ids])

    def get_decision_history(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Seitenweiser Verlauf über die letzten 24 Stunden, neueste zuerst."""
        client = self._client()
        if client is None:
            return []

        limit = max(1, min(limit, 1000))
        offset = max(0, offset)

        try:
            ids = client.zrevrange(ATTACKS_KEY, offset, offset + limit - 1)
        except Exception as exc:
            logger.error("Verlauf konnte nicht gelesen werden: %s", exc)
            return []

        return self._load_payloads([str(i) for i in ids])

    def get_history_count(self) -> int:
        """Anzahl der Angriffe im 24-h-Fenster."""
        client = self._client()
        if client is None:
            return 0
        try:
            return int(client.zcard(ATTACKS_KEY))
        except Exception as exc:
            logger.error("Verlaufsanzahl konnte nicht ermittelt werden: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # Lesepfad: Aggregate
    # ------------------------------------------------------------------
    @staticmethod
    def _recent_hours(now: Optional[float] = None) -> List[int]:
        """Die ``WINDOW_HOURS`` Stunden bis einschließlich der laufenden."""
        current = _hour_of(now if now is not None else time.time())
        return [current - offset for offset in range(WINDOW_HOURS - 1, -1, -1)]

    def _country_totals(self) -> List[Tuple[str, int]]:
        """Ländervereinigung über die Stundeneimer, absteigend sortiert.

        ``ZUNIONSTORE`` rechnet im Server; übertragen wird nur das Ergebnis.
        Das Zwischenergebnis wird kurz zwischengespeichert, damit häufige
        Abfragen die Vereinigung nicht jedes Mal neu bilden.
        """
        client = self._client()
        if client is None:
            return []

        try:
            if not client.exists(COUNTRIES_CACHE_KEY):
                keys = [_countries_key(hour) for hour in self._recent_hours()]
                pipe = client.pipeline(transaction=False)
                pipe.zunionstore(COUNTRIES_CACHE_KEY, keys)
                pipe.expire(COUNTRIES_CACHE_KEY, COUNTRIES_CACHE_TTL)
                pipe.execute()

            entries = client.zrevrange(COUNTRIES_CACHE_KEY, 0, -1, withscores=True)
        except Exception as exc:
            logger.error("Länderstatistik konnte nicht gebildet werden: %s", exc)
            return []

        return [(str(country), int(score)) for country, score in entries]

    def _count_since(self, seconds: int) -> int:
        """Anzahl der Angriffe der letzten ``seconds`` Sekunden."""
        client = self._client()
        if client is None:
            return 0
        try:
            return int(client.zcount(ATTACKS_KEY, time.time() - seconds, "+inf"))
        except Exception as exc:
            logger.error("Angriffe konnten nicht gezählt werden: %s", exc)
            return 0

    def get_total_attacks_24h(self) -> int:
        return self._count_since(TTL_24H)

    def get_attacks_last_hour(self) -> int:
        return self._count_since(HOUR)

    def get_unique_countries_24h(self) -> int:
        return len(self._country_totals())

    def get_country_counts_24h(self) -> Dict[str, int]:
        return dict(self._country_totals())

    def get_decisions_by_country(self) -> Dict[str, Any]:
        """Antwort für ``GET /api/v1/country``.

        ``attacks_per_hour`` ist die tatsächliche Anzahl der letzten 60 Minuten
        und damit die aktuelle Rate - nicht mehr der 24-h-Durchschnitt.
        """
        client = self._client()
        if client is None:
            return {"status": "error", "message": "Redis client not initialized"}

        try:
            countries = self._country_totals()
            return {
                "status": "success",
                "metadata": {
                    "total_attacks": self.get_total_attacks_24h(),
                    "unique_countries": len(countries),
                    "attacks_per_hour": self.get_attacks_last_hour(),
                },
                "countries": [{country: count} for country, count in countries],
            }
        except Exception as exc:
            logger.error("Länderabfrage fehlgeschlagen: %s", exc)
            return {"status": "error", "message": "An internal error occurred"}

    def get_timeline_24h(self) -> List[Dict[str, Any]]:
        """Angriffe je Stunde für die letzten 24 Stunden, älteste zuerst.

        Liest die vorberechneten Stundenzähler - ein ``MGET`` statt tausender
        Einzelereignisse.
        """
        client = self._client()
        if client is None:
            return []

        hours = self._recent_hours()
        try:
            values = client.mget([_total_key(hour) for hour in hours])
        except Exception as exc:
            logger.error("Zeitverlauf konnte nicht gelesen werden: %s", exc)
            return []

        current_hour = hours[-1]
        timeline: List[Dict[str, Any]] = []
        for hour, raw in zip(hours, values):
            try:
                count = int(raw) if raw is not None else 0
            except (TypeError, ValueError):
                count = 0
            timeline.append(
                {
                    "hour_start": self._iso_hour(hour),
                    "hours_ago": current_hour - hour,
                    "count": count,
                }
            )
        return timeline

    @staticmethod
    def _iso_hour(hour: int) -> str:
        return datetime.fromtimestamp(hour * HOUR, settings.tz).isoformat()

    # ------------------------------------------------------------------
    # Wartung
    # ------------------------------------------------------------------
    def clear_all(self) -> bool:
        """Löscht alle Daten des Dashboards, einschließlich alter Schlüssel."""
        client = self._client()
        if client is None:
            return False

        try:
            keys = [ATTACKS_KEY, COUNTRIES_CACHE_KEY, *LEGACY_KEYS]
            for hour in self._recent_hours():
                keys.append(_countries_key(hour))
                keys.append(_total_key(hour))

            pipe = client.pipeline(transaction=False)
            pipe.delete(*keys)
            # Nutzdaten laufen zwar von allein ab, werden hier aber sofort entfernt.
            for batch in self._scan_payload_keys(client):
                pipe.delete(*batch)
            pipe.execute()

            logger.info("Alle Dashboard-Daten aus Redis entfernt")
            return True
        except Exception as exc:
            logger.error("Aufräumen fehlgeschlagen: %s", exc)
            return False

    @staticmethod
    def _scan_payload_keys(
        client: redis.Redis, batch_size: int = 500
    ) -> Iterator[List[str]]:
        """Iteriert die Nutzdaten-Schlüssel per ``SCAN`` statt per ``KEYS``."""
        batch: List[str] = []
        for key in client.scan_iter(match=f"{ATTACK_PAYLOAD_PREFIX}*", count=batch_size):
            batch.append(str(key))
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch


_redis_client: Optional[RedisClient] = None


def get_redis_client() -> RedisClient:
    """Liefert die gemeinsam genutzte Redis-Client-Instanz."""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client
