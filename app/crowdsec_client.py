"""CrowdSec API Client with stream listener"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from requests.exceptions import RequestException, Timeout

from app.config import settings
from app.redis_client import get_redis_client

logger = logging.getLogger(__name__)


#: Abstand zwischen zwei Abfragen der Alert-Liste.
POLL_INTERVAL = 1.25
#: Wartezeit nach einem Fehler, bevor erneut versucht wird.
ERROR_BACKOFF = 5
#: So viele Alerts werden pro Abfrage geholt.
ALERT_PAGE_SIZE = 10


class CrowdSecClient:
    """Client for interacting with CrowdSec API"""

    def __init__(self):
        # Zustand gehört an die Instanz - als Klassenattribute würden ihn
        # mehrere Clients unbemerkt teilen.
        self.API_KEY: str = ""
        self.KEY_RENEWAL_AT: Optional[datetime] = None
        self.last_decision_id: Optional[int] = None
        self._last_renewal_print: Optional[datetime] = None

        self.base_url = settings.crowdsec_host.rstrip("/")
        self.tls_cert = str(settings.tls_cert_path)
        self.tls_key = str(settings.tls_key_path)
        self.tls_ca = str(settings.tls_ca_path)
        self.timeout = 30

        # Validate TLS certificates on initialization
        is_valid, message = settings.validate_tls_certificates()
        if not is_valid:
            logger.error(f"TLS Certificate Validation Failed:\n{message}")
        else:
            logger.info(f"TLS Certificates validated successfully")
            logger.debug(f"Using certificate: {self.tls_cert}")
            logger.debug(f"Using key: {self.tls_key}")
            logger.debug(f"Using CA: {self.tls_ca}")

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        return {
            "Content-Type": "application/json",
            "User-Agent": "Sectacho/0.1.0",
            "Authorization": f"Bearer {self.API_KEY}",
        }

    def _make_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        timeout: int = 30,
        data: Optional[str] = None,
    ):
        """
        Make synchronous HTTP request using requests library

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            url: Full URL for the request
            headers: Request headers
            params: Query parameters
            json: JSON payload
            stream: Whether to stream the response

        Returns:
            Response object or iterator if streaming
        """
        try:
            # Make the request
            response = requests.request(
                method=method,
                url=url,
                cert=(self.tls_cert, self.tls_key),
                verify=self.tls_ca,
                headers=headers,
                params=params,
                json=json,
                timeout=timeout,
                stream=stream,
                data=data,
            )

            response.raise_for_status()
            return response

        except Timeout as e:
            logger.error(f"Timeout during {method} request to {url}: {e}")
            return None
        except RequestException as e:
            logger.error(f"HTTP error during {method} request to {url}: {e}")
            if hasattr(e, "response") and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error during {method} request: {type(e).__name__}: {e}"
            )
            import traceback

            logger.debug(f"Traceback: {traceback.format_exc()}")
            return None

    def stream_decisions(self) -> None:
        """
        Stream decisions from CrowdSec /decisions/stream endpoint
        This is a blocking call that continuously listens for new decisions
        """

        def get_apikey():
            response = self._make_request(
                "POST",
                f"{self.base_url}/v1/watchers/login",
                self._get_headers(),
                data="""{
                    "scenarios": [
                        "ban"
                    ]
                }""",
            )
            if response is None:
                logger.error("Failed to obtain API key")
                return

            response_data = response.json()
            # Parse expire time in a timezone-aware manner; if missing, set to now + 10min
            expire_raw = response_data.get(
                "expire", (datetime.now(settings.tz) + timedelta(minutes=10)).isoformat()
            )
            try:
                # Try parsing with timezone info
                expire_dt = datetime.fromisoformat(expire_raw)
            except Exception:
                # Fallback: parse without tz and attach configured tz
                try:
                    expire_dt = datetime.strptime(expire_raw, "%Y-%m-%dT%H:%M:%S")
                    expire_dt = expire_dt.replace(tzinfo=settings.tz)
                except Exception:
                    expire_dt = datetime.now(settings.tz) + timedelta(minutes=10)

            self.KEY_RENEWAL_AT = expire_dt.astimezone(settings.tz).replace(microsecond=0)
            self.API_KEY = response_data.get("token", "")
            # Das Token ist ein Geheimnis und gehört nicht ins Log.
            logger.info("Obtained API key for decision stream")

        url = (
            f"{self.base_url}/v1/alerts"
            f"?simulated=false&has_active_decision=true&limit={ALERT_PAGE_SIZE}"
        )
        headers = self._get_headers()
        redis_client = get_redis_client()

        get_apikey()
        if self.KEY_RENEWAL_AT:
            logger.info(f"API key will be renewed at {self.KEY_RENEWAL_AT.isoformat()}")

        logger.info(f"Starting CrowdSec decision stream from {url}")
        while True:
            now = datetime.now(settings.tz)
            if self._last_renewal_print is None or now - self._last_renewal_print >= timedelta(
                minutes=5
            ):
                if self.KEY_RENEWAL_AT:
                    renewal_in = self.KEY_RENEWAL_AT - timedelta(minutes=5) - now
                    logger.info(f"Renewal in: {renewal_in}")
                self._last_renewal_print = now
            if self.KEY_RENEWAL_AT and now >= (self.KEY_RENEWAL_AT - timedelta(minutes=5)):
                logger.info("Renewing API key for decision stream")
                get_apikey()
                if not self.API_KEY:
                    # Ohne Wartezeit würde ein fehlgeschlagener Login die
                    # Schleife ohne Pause durchlaufen lassen.
                    time.sleep(ERROR_BACKOFF)
                continue
            try:
                headers = self._get_headers()  # Refresh headers with current API_KEY
                response = self._make_request("GET", url, headers)

                if response is None:
                    logger.error(
                        "Failed to connect to decisions stream, retrying in %ss...",
                        ERROR_BACKOFF,
                    )
                    time.sleep(ERROR_BACKOFF)
                    continue

                stored = self._store_new_alerts(response.json(), redis_client)
                if stored:
                    logger.info("Stored %s new decision(s)", stored)

                time.sleep(POLL_INTERVAL)

            except Exception as e:
                logger.error(f"Error in decision stream: {type(e).__name__}: {e}")
                time.sleep(ERROR_BACKOFF)

    def _store_new_alerts(self, alerts: Any, redis_client: Any) -> int:
        """Speichert alle Alerts, die neuer sind als der zuletzt gesehene.

        Bisher wurde nur ``alerts[0]`` betrachtet. Trafen zwischen zwei
        Abfragen mehrere Alerts ein, gingen alle bis auf den neuesten
        verloren. Die Liste kommt absteigend nach ID, wird hier aber
        aufsteigend verarbeitet, damit die Reihenfolge im Verlauf stimmt.
        """
        if not isinstance(alerts, list) or not alerts:
            return 0

        fresh: List[Dict[str, Any]] = []
        for alert in alerts:
            alert_id = self._alert_id(alert)
            if alert_id is None:
                continue
            if self.last_decision_id is not None and alert_id <= self.last_decision_id:
                continue
            fresh.append(alert)

        if not fresh:
            return 0

        fresh.sort(key=lambda item: self._alert_id(item) or 0)

        stored = 0
        for alert in fresh:
            alert_id = self._alert_id(alert)
            source = alert.get("source") or {}
            latitude = source.get("latitude")
            longitude = source.get("longitude")
            if latitude is None or longitude is None:
                logger.debug("Alert %s ohne Koordinaten, übersprungen", alert_id)
                continue

            data = {
                "latitude": latitude,
                "longitude": longitude,
                "cn": source.get("cn", ""),
                "timestamp": datetime.now(settings.tz).isoformat(),
            }
            if redis_client.add_decision(data, str(alert_id)):
                stored += 1

        # Auch übersprungene Alerts gelten als gesehen, sonst werden sie bei
        # jeder Abfrage erneut geprüft.
        newest = self._alert_id(fresh[-1])
        if newest is not None:
            self.last_decision_id = newest

        return stored

    @staticmethod
    def _alert_id(alert: Any) -> Optional[int]:
        """CrowdSec-Alert-IDs sind aufsteigende Ganzzahlen."""
        if not isinstance(alert, dict):
            return None
        try:
            return int(alert["id"])
        except (KeyError, TypeError, ValueError):
            return None


# Create global client instance
_client: Optional[CrowdSecClient] = None


def get_client() -> CrowdSecClient:
    """Get or create CrowdSec client"""
    global _client
    if _client is None:
        _client = CrowdSecClient()
    return _client


def start_stream_listener() -> None:
    """Start the stream listener (blocking)"""
    client = get_client()
    client.stream_decisions()
