"""Country aggregation API endpoints"""

import logging

from fastapi import APIRouter

from app.redis_client import get_redis_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/country")
async def get_country_stats():
    """
    Get aggregated attack counts by country.
    
    Returns countries sorted by attack count in descending order.
    Format: [{"CN": 145}, {"US": 98}, {"RU": 67}, ...]
    
    Each entry contains:
    - Country code (ISO 3166-1 alpha-2): number of attacks
    
    Results are sorted by count (highest first).
    """
    redis_client = get_redis_client()
    if not redis_client:
        return {"status": "error", "message": "Redis client not initialized"}

    try:
        return redis_client.get_decisions_by_country()
    except Exception as e:
        logger.error(f"Error fetching country decisions: {e}")
        return {"status": "error", "message": "Failed to fetch country decisions"}
