"""
HTTP client utilities for dcmon client.

Provides a clean interface for making HTTP requests to the dcmon server,
including SSL context handling and JSON serialization.
"""

import json
import ssl
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen


class DCMonHttpClient:
    """HTTP client for communicating with dcmon server."""

    def __init__(self, server_base: str, timeout: int = 10):
        """
        Initialize HTTP client.

        Args:
            server_base: Base URL of the dcmon server (e.g., https://server:8000)
            timeout: Request timeout in seconds
        """
        self.server_base = server_base.rstrip("/")
        self.timeout = timeout
        self._ssl_context = self._create_ssl_context()

    def _create_ssl_context(self) -> ssl.SSLContext:
        """Create SSL context for HTTPS that auto-trusts server certificates."""
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    def post_json(self, endpoint: str, data: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Make a POST request with JSON data.

        Args:
            endpoint: API endpoint path (e.g., /api/metrics)
            data: Dictionary to send as JSON
            headers: Optional additional headers

        Returns:
            Response data as dictionary

        Raises:
            HTTPError: On HTTP errors
            URLError: On connection errors
        """
        url = f"{self.server_base}{endpoint}"
        body = json.dumps(data).encode("utf-8")
        hdrs = {"Content-Type": "application/json"}
        hdrs.update(headers or {})
        req = Request(url, data=body, headers=hdrs, method="POST")

        # Use SSL context for HTTPS URLs
        ssl_context = self._ssl_context if url.startswith("https://") else None

        with urlopen(req, timeout=self.timeout, context=ssl_context) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def get_json(self, endpoint: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Make a GET request.

        Args:
            endpoint: API endpoint path
            headers: Optional request headers

        Returns:
            Response data as dictionary

        Raises:
            HTTPError: On HTTP errors
            URLError: On connection errors
        """
        url = f"{self.server_base}{endpoint}"
        req = Request(url, headers=headers or {}, method="GET")

        # Use SSL context for HTTPS URLs
        ssl_context = self._ssl_context if url.startswith("https://") else None

        with urlopen(req, timeout=self.timeout, context=ssl_context) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def send_metrics(
        self,
        client_token: str,
        metrics: List[Dict[str, Any]],
        hw_hash: Optional[str] = None,
        logs: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Send metrics (and optionally logs) to the server.

        Args:
            client_token: Client authentication token
            metrics: List of metric dictionaries
            hw_hash: Optional hardware hash for change detection
            logs: Optional list of log entries

        Returns:
            Server response with received/inserted counts
        """
        if not metrics:
            return {"received": 0, "inserted": 0}

        headers = {"Authorization": f"Bearer {client_token}"}
        data = {"metrics": metrics}

        if hw_hash:
            data["hw_hash"] = hw_hash
        if logs:
            data["logs"] = logs

        return self.post_json("/api/metrics", data, headers)
