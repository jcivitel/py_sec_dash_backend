"""Health check endpoint"""
import logging

from fastapi import APIRouter

from app.redis_client import get_redis_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Sectacho API"}


@router.get("/health/redis")
async def health_check_redis():
    """Redis health check"""
    try:
        redis_client = get_redis_client()
        if redis_client.redis_client:
            redis_client.redis_client.ping()
            return {"status": "healthy", "redis": "connected"}
        else:
            return {"status": "unhealthy", "redis": "not initialized"}
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return {"status": "unhealthy", "redis": "connection failed"}
