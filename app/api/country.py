"""Alerts API endpoints"""

import logging

from fastapi import APIRouter

from app.redis_client import get_redis_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/country")
async def cout_country():
    """Get list of country decisions from Redis"""
    redis_client = get_redis_client()
    if not redis_client:
        return {"error": "Redis client not initialized"}

    try:
        return redis_client.get_decisions_by_country()
    except Exception as e:
        logger.error(f"Error fetching country decisions: {e}")
        return {"error": "Failed to fetch country decisions"}
