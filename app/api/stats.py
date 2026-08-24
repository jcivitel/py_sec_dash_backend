"""Aggregierte Kennzahlen über den Zeitverlauf"""

import logging

from fastapi import APIRouter

from app.redis_client import get_redis_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/timeline")
async def get_timeline():
    """Angriffe je Stunde für die letzten 24 Stunden.

    Liefert 24 Einträge, ältester zuerst. Die Werte stammen aus vorberechneten
    Stundenzählern - der Aufruf ist unabhängig von der Menge gespeicherter
    Angriffe konstant teuer.

    Jeder Eintrag enthält:
    - hour_start: Beginn der Stunde als ISO-8601-Zeitstempel
    - hours_ago: Abstand zur laufenden Stunde (23 ... 0)
    - count: Anzahl der Angriffe in dieser Stunde
    """
    try:
        redis_client = get_redis_client()
        timeline = redis_client.get_timeline_24h()
        return {
            "status": "success",
            "timeline": timeline,
            "total": sum(entry["count"] for entry in timeline),
        }
    except Exception as e:
        logger.error(f"Error fetching timeline: {e}")
        return {"status": "error", "message": "Failed to fetch timeline"}
