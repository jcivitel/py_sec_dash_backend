"""Redis client for storing CrowdSec decisions"""

import json
import logging
from typing import List, Dict, Any, Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)

# Redis keys
DECISIONS_HASH_KEY = "crowdsec:decisions:hash"  # Hash für einzelne Decisions mit eindeutiger ID (20s TTL)
COUNTRY_HASH_KEY = "crowdsec:country:counts"    # Hash für Länderzählungen (24h TTL)
TOTAL_ATTACKS_KEY = "crowdsec:total:attacks"    # Counter für alle Angriffe (persistent, kein TTL)
UNIQUE_COUNTRIES_SET_KEY = "crowdsec:unique:countries"  # Set aller Länder (persistent, kein TTL)
DECISIONS_HISTORY_LIST_KEY = "crowdsec:decisions:history"  # Sorted Set für historische Decisions mit Timestamp (7 Tage TTL)


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

    def add_decision(self, decision_data: Dict[str, Any], decision_id: str) -> bool:
        """
        Add a new decision to Redis with a unique ID.

        Args:
            decision_data: Decision object from CrowdSec API
            decision_id: Unique identifier for this decision (from CrowdSec)

        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.redis_client:
                logger.error("Redis client not initialized")
                return False

            # Store decision in hash with unique ID as field
            self.redis_client.hset(
                DECISIONS_HASH_KEY,
                decision_id,
                json.dumps(decision_data)
            )
            
            # Set expiration to 20 seconds for the entire hash
            self.redis_client.expire(DECISIONS_HASH_KEY, 20)

            # Update persistent counter for total attacks (only count new decisions)
            try:
                self._increment_total_attacks()
            except Exception as e:
                logger.error(f"Failed to increment total attacks counter: {e}")

            # Update country counts and unique countries set
            country = decision_data.get("cn")
            if country:
                try:
                    self._increment_country_count(country)
                    self._add_unique_country(country)
                except Exception as e:
                    logger.error(
                        f"Failed to update country data for {country}: {e}"
                    )

            # Store decision in history with timestamp for pagination
            try:
                self._add_to_history(decision_id, decision_data)
            except Exception as e:
                logger.error(f"Failed to add decision to history: {e}")

            logger.debug(
                f"Added decision with ID {decision_id} for country {decision_data.get('cn', 'unknown')}"
            )
            return True

        except Exception as e:
            logger.error(f"Error adding decision to Redis: {e}")
            return False

    def _increment_total_attacks(self) -> None:
        """
        Increment the persistent counter for total attacks.
        
        Implementation detail:
        - Uses Redis STRING to store counter: TOTAL_ATTACKS_KEY = integer count
        - **NO TTL** - counter persists indefinitely
        - Increments by 1 for each new decision
        """
        if not self.redis_client:
            raise RuntimeError("Redis client not initialized")

        # Increment the persistent counter
        self.redis_client.incr(TOTAL_ATTACKS_KEY)
        logger.debug(f"Total attacks counter incremented")

    def _add_unique_country(self, country: str) -> None:
        """
        Add country code to the set of unique countries.
        
        Implementation detail:
        - Uses Redis SET to store unique countries
        - **NO TTL** - set persists indefinitely
        - Automatically handles duplicates (set property)
        """
        if not self.redis_client:
            raise RuntimeError("Redis client not initialized")

        # Add country to set (duplicates are ignored)
        self.redis_client.sadd(UNIQUE_COUNTRIES_SET_KEY, country)
        logger.debug(f"Added country to unique set: {country}")

    def _increment_country_count(self, country: str) -> None:
        """
        Increment the count for a country code in the country hash.

        Implementation detail:
        - Uses Redis HASH to store country counts: field = country code, value = count
        - Automatically creates entry if not exists
        - TTL = 24 hours
        """
        if not self.redis_client:
            raise RuntimeError("Redis client not initialized")

        # Increment the counter for this country
        self.redis_client.hincrby(COUNTRY_HASH_KEY, country, 1)
        
        # Set expiration to 24 hours
        self.redis_client.expire(COUNTRY_HASH_KEY, 86400)

    def get_latest_decisions(self, count: int = 20) -> List[Dict[str, Any]]:
        """
        Get the latest decisions from Redis as array of objects with ID as key.

        Args:
            count: Number of decisions to return (default 20)

        Returns:
            List of decision objects in format [{"id": {...}}, {"id2": {...}}]
        """
        try:
            if not self.redis_client:
                logger.error("Redis client not initialized")
                return []

            # Get all decisions from hash
            all_decisions_dict = self.redis_client.hgetall(DECISIONS_HASH_KEY)  # type: ignore[no-untyped-call]
            
            if not all_decisions_dict:
                return []

            # Convert to list of single-key dicts: [{"id": data}, {"id2": data}, ...]
            result: List[Dict[str, Any]] = []
            item_count = 0
            decisions_items = list(all_decisions_dict.items())  # type: ignore[union-attr]
            for decision_id, decision_json in decisions_items:
                if item_count >= count:
                    break
                try:
                    decision_data = json.loads(str(decision_json))
                    result.append({decision_id: decision_data})
                    item_count += 1
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse decision {decision_id}")
                    continue
            
            return result

        except Exception as e:
            logger.error(f"Error retrieving decisions from Redis: {e}")
            return []

    def _add_to_history(self, decision_id: str, decision_data: Dict[str, Any]) -> None:
        """
        Add decision to history sorted set.
        
        Implementation detail:
        - Uses Redis Sorted Set with timestamp as score
        - Stores decision as JSON with ID as member
        - TTL = 7 days for history
        """
        if not self.redis_client:
            raise RuntimeError("Redis client not initialized")
        
        try:
            import time
            timestamp = time.time()  # Current timestamp as score
            
            # Add to sorted set with timestamp as score
            self.redis_client.zadd(
                DECISIONS_HISTORY_LIST_KEY,
                {f"{decision_id}:{json.dumps(decision_data)}": timestamp}
            )
            
            # Set expiration to 7 days (604800 seconds)
            self.redis_client.expire(DECISIONS_HISTORY_LIST_KEY, 604800)
            logger.debug(f"Added decision {decision_id} to history")
        except Exception as e:
            logger.error(f"Failed to add decision to history: {e}")
            raise

    def get_decision_history(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Get paginated decision history from Redis sorted set.
        
        Args:
            limit: Number of decisions to return (max 1000)
            offset: Number of decisions to skip
        
        Returns:
            List of decision objects in format [{"id": {...}}, {"id2": {...}}]
        """
        try:
            if not self.redis_client:
                logger.error("Redis client not initialized")
                return []
            
            # Clamp limit to reasonable value
            limit = min(limit, 1000)
            
            # Get range from sorted set (reversed to get newest first)
            # ZREVRANGE returns from highest to lowest score
            history_items: Any = self.redis_client.zrevrange(  # type: ignore[no-untyped-call]
                DECISIONS_HISTORY_LIST_KEY,
                offset,
                offset + limit - 1,
                withscores=False
            )
            
            if not history_items:
                return []
            
            result: List[Dict[str, Any]] = []
            for item in history_items:  # type: ignore[union-attr]
                try:
                    # Parse the stored format: "id:json_data"
                    item_str = str(item)
                    if ":" in item_str:
                        decision_id, decision_json = item_str.split(":", 1)
                        decision_data = json.loads(decision_json)
                        result.append({decision_id: decision_data})
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Failed to parse history item: {e}")
                    continue
            
            return result
        
        except Exception as e:
            logger.error(f"Error retrieving decision history: {e}")
            return []

    def get_history_count(self) -> int:
        """Get total number of decisions in history"""
        try:
            if not self.redis_client:
                return 0
            
            count: Any = self.redis_client.zcard(DECISIONS_HISTORY_LIST_KEY)  # type: ignore[no-untyped-call]
            return int(count) if count else 0
        except Exception as e:
            logger.error(f"Error getting history count: {e}")
            return 0

    def clear_all(self) -> bool:
        """Clear all data from Redis"""
        try:
            if not self.redis_client:
                return False
            self.redis_client.delete(
                DECISIONS_HASH_KEY,
                COUNTRY_HASH_KEY,
                TOTAL_ATTACKS_KEY,
                UNIQUE_COUNTRIES_SET_KEY,
                DECISIONS_HISTORY_LIST_KEY
            )
            logger.info("Cleared all decisions, country counts, and metrics from Redis")
            return True
        except Exception as e:
            logger.error(f"Error clearing Redis: {e}")
            return False

    def get_decisions_by_country(self):
        """
        Get aggregated country counts from Redis hash with metadata.

        Returns:
            Dict with status, metadata (total_attacks, unique_countries, attacks_per_hour), 
            and countries list sorted by count (descending)
        """
        try:
            if not self.redis_client:
                logger.error("Redis client not initialized")
                return {
                    "status": "error",
                    "message": "Redis client not initialized",
                }

            # Get all country counts from hash
            country_counts = self.redis_client.hgetall(COUNTRY_HASH_KEY)  # type: ignore[no-untyped-call]
            
            # Get persistent metrics
            total_attacks = 0
            total_attacks_str = self.redis_client.get(TOTAL_ATTACKS_KEY)  # type: ignore[no-untyped-call]
            if total_attacks_str:
                try:
                    total_attacks = int(str(total_attacks_str))
                except (ValueError, TypeError):
                    total_attacks = 0
            
            unique_countries = 0
            unique_countries_set = self.redis_client.smembers(UNIQUE_COUNTRIES_SET_KEY)  # type: ignore[no-untyped-call]
            if unique_countries_set:
                try:
                    unique_countries = len(list(unique_countries_set))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    unique_countries = 0
            
            # Calculate attacks per hour (total / 24)
            attacks_per_hour = total_attacks // 24 if total_attacks > 0 else 0
            
            # Build metadata
            metadata = {
                "total_attacks": total_attacks,
                "unique_countries": unique_countries,
                "attacks_per_hour": attacks_per_hour,
            }
            
            if not country_counts:
                return {
                    "status": "success",
                    "metadata": metadata,
                    "countries": []
                }

            # Convert to list of {"country_code": count} dicts and sort by count descending
            countries_list = []
            items_list = list(country_counts.items())  # type: ignore[union-attr]
            for country, count_str in items_list:
                try:
                    count = int(count_str)
                    countries_list.append({country: count})
                except (ValueError, TypeError):
                    logger.warning(f"Invalid count for country {country}: {count_str}")
                    continue
            
            # Sort by count (value) in descending order
            countries_list.sort(key=lambda x: list(x.values())[0], reverse=True)

            return {
                "status": "success",
                "metadata": metadata,
                "countries": countries_list
            }

        except Exception as e:
            logger.error(f"Error aggregating decisions by country: {e}")
            return {
                "status": "error",
                "message": "An internal error occurred"
            }


# Global Redis client instance
_redis_client: Optional[RedisClient] = None


def get_redis_client() -> RedisClient:
    """Get or create Redis client"""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client
