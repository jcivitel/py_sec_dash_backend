"""Alerts API endpoints"""
import logging

from fastapi import APIRouter

from app.redis_client import get_redis_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/decisions")
async def get_latest_decisions():
    """
    Get the latest decision from Redis

    """

    try:
        redis_client = get_redis_client()
        decisions = redis_client.get_latest_decisions()
        return {
            "status": "success",
            "decision": decisions
        }
    except Exception as e:
        logger.error(f"Error fetching decisions: {e}")
        return {
            "status": "error",
            "message": str(e),
            "decisions": []
        }
