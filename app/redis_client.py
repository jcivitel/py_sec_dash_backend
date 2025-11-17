"""Redis client for storing CrowdSec decisions"""

import json
import logging
from typing import List, Dict, Any, Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)

# Redis keys
DECISIONS_KEY = "crowdsec:decisions"
COUNTRY_KEY = "crowdsec:country"


class RedisClient:
    """Client for Redis operations"""

    def __init__(self):
        """Initialize Redis connection"""
        try:
            self.redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password if settings.redis_password else None,
                decode_responses=True,
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None

    def add_decision(self, decision_data: Dict[str, Any], id: int) -> bool:
        """
        Add a new decision to Redis

        Args:
            decision_data: Decision object from CrowdSec API

        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.redis_client:
                logger.error("Redis client not initialized")
                return False

            # Create entry with timestamp
            entry = {
                id: decision_data,
            }

            # Push to list (left push = newest first)
            self.redis_client.lpush(DECISIONS_KEY, json.dumps(entry))
            # Set expiration to 20 seconds
            self.redis_client.expire(DECISIONS_KEY, 20)

            # --- Neuer Block: Länderzählung in COUNTRY_KEY pflegen ---
            country = decision_data.get("cn")
            if country:
                try:
                    # Erhöhe den Zähler für dieses Länder-Kürzel in der COUNTRY_KEY-Liste
                    self._increment_country_count(country)
                except Exception as e:
                    logger.error(
                        f"Failed to increment country count for {country}: {e}"
                    )
            # --- Ende Länderzählung ---

            logger.debug(
                f"Added decision for IP {decision_data.get('value', 'unknown')}"
            )
            return True

        except Exception as e:
            logger.error(f"Error adding decision to Redis: {e}")
            return False

    def _increment_country_count(self, country: str) -> None:
        """
        Private helper to increment the count for a country code stored in a Redis list (COUNTRY_KEY).

        Implementation detail:
        - The COUNTRY_KEY list contains JSON objects like {"US": 5}, each element representing one country.
        - We scan the list for an entry that contains the country key, increment it with LSET, or RPUSH a new entry if not found.
        """
        if not self.redis_client:
            raise RuntimeError("Redis client not initialized")

        # Get all country entries
        entries = self.redis_client.lrange(COUNTRY_KEY, 0, -1)

        for idx, item_json in enumerate(entries):
            try:
                obj = json.loads(item_json)
            except Exception:
                # Skip malformed entries
                continue

            if country in obj:
                # Increment and replace this list element
                obj[country] = int(obj.get(country, 0)) + 1
                self.redis_client.lset(COUNTRY_KEY, idx, json.dumps(obj))
                # Refresh expiration (optional): 1 hour
                self.redis_client.expire(COUNTRY_KEY, 86400)
                return

        # If not found, append a new entry
        self.redis_client.rpush(COUNTRY_KEY, json.dumps({country: 1}))
        self.redis_client.expire(COUNTRY_KEY, 86400)

    def get_latest_decisions(self, count: int = 20) -> List[Dict[str, Any]]:
        """
        Get the latest decisions from Redis

        Args:
            count: Number of decisions to return (default 20)

        Returns:
            List of decision objects
        """
        try:
            if not self.redis_client:
                logger.error("Redis client not initialized")
                return []

            # Get entries from list (0 to count-1)
            entries = self.redis_client.lrange(DECISIONS_KEY, 0, count - 1)
            entries_decoded = [json.loads(entry_json) for entry_json in entries]
            return entries_decoded

        except Exception as e:
            logger.error(f"Error retrieving decisions from Redis: {e}")
            return []

    def clear_all(self) -> bool:
        """Clear all decisions from Redis"""
        try:
            if not self.redis_client:
                return False
            self.redis_client.delete(DECISIONS_KEY)
            logger.info("Cleared all decisions from Redis")
            return True
        except Exception as e:
            logger.error(f"Error clearing Redis: {e}")
            return False

    def get_decisions_by_country(self):
        """
        Aggregate decisions by country (cn) and return counts.

        Args:
            count: number of latest decisions to scan from Redis (default 100)

        Returns:

            Dict with status, total count and a list of {"cn": country_code, "count": n}
        """
        try:
            if not self.redis_client:
                logger.error("Redis client not initialized")
                return {
                    "status": "error",
                    "message": "Redis client not initialized",
                    "count": 0,
                    "decisions": [],
                }

            # Read aggregated country counts from COUNTRY_KEY list
            entries = self.redis_client.lrange(COUNTRY_KEY, 0, -1)
            # Jeder Eintrag ist ein Byte/String → zu Python-Objekten wandeln
            decoded_entries = [json.loads(entry) for entry in entries]

            return {"status": "success", "countries": decoded_entries}

        except Exception as e:
            logger.error(f"Error aggregating decisions by country: {e}")
            return {"status": "error", "message": "An internal error occurred", "count": 0, "decisions": []}


# Global Redis client instance
_redis_client: Optional[RedisClient] = None


def get_redis_client() -> RedisClient:
    """Get or create Redis client"""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client
