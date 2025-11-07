"""CrowdSec API Client with stream listener"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import requests
from requests.exceptions import RequestException, Timeout

from app.config import settings
from app.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class CrowdSecClient:
    """Client for interacting with CrowdSec API"""
    API_KEY = ""
    KEY_RENEWAL_AT = None
    last_decision_id = None

    def __init__(self):
        self.base_url = settings.crowdsec_host.rstrip('/')
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
            "Authorization": f"Bearer {self.API_KEY}"
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
            data: Optional[str] = None
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
                data=data
            )

            response.raise_for_status()
            return response

        except Timeout as e:
            logger.error(f"Timeout during {method} request to {url}: {e}")
            return None
        except RequestException as e:
            logger.error(f"HTTP error during {method} request to {url}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during {method} request: {type(e).__name__}: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            return None

    def stream_decisions(self) -> None:
        """
        Stream decisions from CrowdSec /decisions/stream endpoint
        This is a blocking call that continuously listens for new decisions
        """

        def get_apikey():
            key = self._make_request(
                "POST",
                f"{self.base_url}/v1/watchers/login",
                headers,
                data="""{
                    "scenarios": [
                        "ban"
                    ]
                }"""),
            self.KEY_RENEWAL_AT = datetime.strptime(key[0].json().get("expire", datetime.now() + timedelta(minutes=10)),
                                                    "%Y-%m-%dT%H:%M:%S%z").strftime("%Y-%m-%dT%H:%M:%S")
            self.API_KEY = key[0].json().get("token", "")
            logger.info(f"Obtained API key for decision stream: {self.API_KEY}")

        url = f"{self.base_url}/v1/alerts?simulated=false&has_active_decision=true&limit=10"
        headers = self._get_headers()
        redis_client = get_redis_client()

        get_apikey()
        logger.info(f"API key will be renewed at {self.KEY_RENEWAL_AT}")

        logger.info(f"Starting CrowdSec decision stream from {url}")
        headers = self._get_headers()
        while True:
            if datetime.now() + timedelta(minutes=5) >= datetime.strptime(self.KEY_RENEWAL_AT, "%Y-%m-%dT%H:%M:%S"):
                logger.info("Renewing API key for decision stream")
                get_apikey()
                continue
            try:
                response = self._make_request(
                    "GET",
                    url + "",
                    headers
                )

                if response is None:
                    logger.error("Failed to connect to decisions stream, retrying in 5 seconds...")
                    import time
                    time.sleep(5)
                    continue
                json_data = response.json()
                if not self.last_decision_id == json_data[0]["id"]:
                    self.last_decision_id = json_data[0]["id"]
                    data = {
                        "latitude": json_data[0]["source"]["latitude"],
                        "longitude": json_data[0]["source"]["longitude"],
                        "cn": json_data[0]["source"]["cn"],
                    }
                    redis_client.add_decision(data, json_data[0]["id"])
                    logger.info("Added new decision")
                else:
                    import time
                    time.sleep(1.25)


            except Exception as e:
                logger.error(f"Error in decision stream: {type(e).__name__}: {e}")
                import time
                time.sleep(5)


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
