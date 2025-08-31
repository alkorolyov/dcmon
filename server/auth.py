#!/usr/bin/env python3
"""
dcmon AuthService (server-side authentication helpers)

Responsibilities (authN only):
- Verify client signatures over the provided challenge string
- Validate registration request shape and freshness
- Issue opaque tokens (client/admin)

Notes:
- Does NOT do authorization (admin checks) — keep that in FastAPI layer.
- Challenge format: any string that ends with ':<timestamp>'.
"""

import base64
import secrets
import time
import logging
from typing import Dict, Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key

logger = logging.getLogger("dcmon.server.auth")


class AuthService:
    def __init__(self, *, skew_seconds: int = 300) -> None:
        self.skew_seconds = int(skew_seconds)

    # ---------- Token issuance ----------

    def generate_client_token(self) -> str:
        """Opaque bearer token for a client."""
        return f"dcmon_{secrets.token_urlsafe(32)}"

    def generate_admin_token(self) -> str:
        """Opaque bearer token for the admin (use in installer)."""
        return f"dcmon_admin_{secrets.token_urlsafe(32)}"

    # ---------- Signature verification ----------

    def verify_signature(self, public_key_pem: str, message: str, signature_b64: str) -> bool:
        """Verify RSASSA-PSS (SHA-256) signature over `message`."""
        try:
            public_key = load_pem_public_key(public_key_pem.encode("utf-8"))
            signature = base64.b64decode(signature_b64)
            public_key.verify(
                signature,
                message.encode("utf-8"),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256(),
            )
            return True
        except Exception as e:
            logger.warning(f"signature verification failed: {e}")
            return False

    # ---------- Registration request validation ----------

    def validate_registration_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a client registration request.

        Required keys:
          - hostname: str
          - public_key: str (PEM)
          - challenge: str (must end with ':<timestamp>')
          - signature: str (base64 signature of challenge)
          - timestamp: int (must match trailing part of challenge)
        """
        result = {"valid": False, "error": "Invalid request", "hostname": None, "public_key": None}

        required = ["hostname", "public_key", "challenge", "signature", "timestamp"]
        for key in required:
            if key not in request:
                result["error"] = f"Missing required field: {key}"
                return result

        hostname = str(request["hostname"])
        public_key = str(request["public_key"])
        challenge = str(request["challenge"])
        signature = str(request["signature"])
        ts = int(request["timestamp"])

        # Freshness
        now = int(time.time())
        if abs(now - ts) > self.skew_seconds:
            result["error"] = "Timestamp out of valid range"
            return result

        # Challenge trailer must match timestamp
        parts = challenge.rsplit(":", 1)
        if len(parts) != 2:
            result["error"] = "Invalid challenge format (missing trailing ':<timestamp>')"
            return result
        try:
            ch_ts = int(parts[1])
        except ValueError:
            result["error"] = "Invalid challenge timestamp"
            return result
        if ch_ts != ts:
            result["error"] = "Challenge timestamp mismatch"
            return result

        if not self.verify_signature(public_key, challenge, signature):
            result["error"] = "Signature verification failed"
            return result

        result.update({"valid": True, "error": None, "hostname": hostname, "public_key": public_key})
        return result


# Convenience singleton
auth_service = AuthService()


if __name__ == "__main__":
    # Utility: print an admin token for installer use
    print(AuthService().generate_admin_token())
