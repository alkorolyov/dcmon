#!/usr/bin/env python3
"""
dcmon Client Utilities

Shared utilities used by multiple client modules to avoid circular imports.
"""

import json
import ssl
from typing import Any, Dict
from urllib.request import Request, urlopen


def create_ssl_context() -> ssl.SSLContext:
    """Create SSL context for HTTPS/WSS that auto-trusts server certificates"""
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return ssl_context


def post_json(url: str, data: Dict[str, Any], headers: Dict[str, str], timeout: int = 10) -> Dict[str, Any]:
    """POST JSON request helper with HTTPS auto-trust support"""
    body = json.dumps(data).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = Request(url, data=body, headers=hdrs, method="POST")
    
    # Use SSL context for HTTPS URLs
    ssl_context = create_ssl_context() if url.startswith("https://") else None
    
    with urlopen(req, timeout=timeout, context=ssl_context) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def get_json(url: str, headers: Dict[str, str], timeout: int = 10) -> Dict[str, Any]:
    """GET JSON request helper with HTTPS auto-trust support"""
    req = Request(url, headers=headers or {}, method="GET")
    
    # Use SSL context for HTTPS URLs
    ssl_context = create_ssl_context() if url.startswith("https://") else None
    
    with urlopen(req, timeout=timeout, context=ssl_context) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}