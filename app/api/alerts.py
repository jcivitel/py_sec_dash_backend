"""Alerts API endpoints"""

import logging

from fastapi import APIRouter, Query

from app.redis_client import get_redis_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/decisions")
async def get_latest_decisions():
    """
    Get the latest decisions from Redis.
    
    Returns decisions as a list of dictionaries where each decision has its unique ID as a key.
    Format: [{"unique_decision_id_1": {...}}, {"unique_decision_id_2": {...}}]
    
    Each decision contains:
    - latitude: Attack source latitude
    - longitude: Attack source longitude
    - cn: ISO 3166-1 alpha-2 country code
    - timestamp: ISO 8601 timestamp
    """

    try:
        redis_client = get_redis_client()
        decisions = redis_client.get_latest_decisions(count=20)
        return {"status": "success", "decision": decisions}
    except Exception as e:
        logger.error(f"Error fetching decisions: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/decisions/history")
async def get_decision_history(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """
    Get paginated decision history from Redis.
    
    Query Parameters:
    - limit: Number of decisions to return (default: 100, max: 1000)
    - offset: Number of decisions to skip (default: 0)
    
    Returns decisions as a list of dictionaries where each decision has its unique ID as a key.
    Format: [{"unique_decision_id_1": {...}}, {"unique_decision_id_2": {...}}]
    
    Each decision contains:
    - latitude: Attack source latitude
    - longitude: Attack source longitude
    - cn: ISO 3166-1 alpha-2 country code
    - timestamp: ISO 8601 timestamp
    """

    try:
        redis_client = get_redis_client()
        decisions = redis_client.get_decision_history(limit=limit, offset=offset)
        total_count = redis_client.get_history_count()
        
        return {
            "status": "success",
            "decision": decisions,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total_count,
                "returned": len(decisions)
            }
        }
    except Exception as e:
        logger.error(f"Error fetching decision history: {e}")
        return {"status": "error", "message": str(e)}
