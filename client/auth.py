#!/usr/bin/env python3
"""
dcmon Client Authentication

- RSA keypair management (2048-bit)
- Registration request creation (aligned with server expectations)
- Client token persistence

Registration request shape (what server expects):
{
  "hostname": "<str>",
  "public_key": "<PEM>",
  "challenge": "<hostname>:<timestamp>",
  "signature": "<base64 PSS-SHA256 of challenge>",
  "timestamp": <unix seconds>
}

NOTE: Paths are rooted at `auth_dir` (default: /etc/dcmon).
"""

import base64
import logging
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

try:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = logging.getLogger("dcmon.client.auth")


class ClientAuth:
    """
    Client-side authentication helper.

    Files (under `auth_dir`, default /etc/dcmon):
      - client.key    (PEM, 0600)
      - client.pub    (PEM, 0644)
      - client_token  (opaque token from server, 0600)
    """

    def __init__(self, auth_dir: Path = Path("/etc/dcmon")) -> None:
        self.auth_dir = Path(auth_dir)
        self.private_key_file = self.auth_dir / "client.key"
        self.public_key_file = self.auth_dir / "client.pub"
        self.token_file = self.auth_dir / "client_token"

        if not CRYPTO_AVAILABLE:
            raise ImportError("cryptography package is required (pip install cryptography)")

    # ---------- Key management ----------

    def generate_key_pair(self) -> bool:
        """Generate a new RSA keypair and write them to disk with proper permissions."""
        try:
            self.auth_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

            private_key = rsa.generate_private_key(
                public_exponent=65537, 
                key_size=2048, 
                backend=default_backend()
            )
            public_key = private_key.public_key()

            # Serialize
            private_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            public_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )

            # Write
            self.private_key_file.write_bytes(private_pem)
            self.private_key_file.chmod(0o600)

            self.public_key_file.write_bytes(public_pem)
            self.public_key_file.chmod(0o644)

            logger.info("generated new RSA keypair (%s, %s)", self.private_key_file, self.public_key_file)
            return True
        except Exception as e:
            logger.error("failed to generate key pair: %s", e)
            return False

    def has_valid_keys(self) -> bool:
        """Quick check that both key files exist and private key loads."""
        try:
            if not (self.private_key_file.exists() and self.public_key_file.exists()):
                return False
            _priv, _ = self.load_keys()
            return _priv is not None
        except Exception:
            return False

    def load_keys(self) -> Tuple[Optional[Any], Optional[str]]:
        """Load the private key object and public key PEM string."""
        try:
            priv_bytes = self.private_key_file.read_bytes()
            private_key = load_pem_private_key(priv_bytes, password=None, backend=default_backend())
            public_pem = self.public_key_file.read_text().strip()
            return private_key, public_pem
        except Exception as e:
            logger.error("failed to load keys: %s", e)
            return None, None

    def get_public_key(self) -> Optional[str]:
        try:
            return self.public_key_file.read_text().strip()
        except Exception:
            return None

    # ---------- Signatures ----------

    def sign(self, data: str) -> Optional[str]:
        """Sign arbitrary data with the client's private key; return base64-encoded signature."""
        try:
            private_key, _ = self.load_keys()
            if not private_key:
                return None
            sig = private_key.sign(
                data.encode("utf-8"),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256(),
            )
            return base64.b64encode(sig).decode("utf-8")
        except Exception as e:
            logger.error("failed to sign data: %s", e)
            return None

    # ---------- Registration request ----------

    def create_registration_request(self, hostname: str) -> Optional[Dict[str, Any]]:
        """
        Build the registration request for the server.

        Challenge format: "<hostname>:<timestamp>"
        Only the trailing ':<timestamp>' is strictly validated on the server.
        """
        try:
            public_key = self.get_public_key()
            if not public_key:
                logger.error("public key not found; generate keys first")
                return None

            ts = int(time.time())
            challenge = f"{hostname}:{ts}"
            signature = self.sign(challenge)
            if not signature:
                return None

            return {
                "hostname": hostname,
                "public_key": public_key,
                "challenge": challenge,
                "signature": signature,
                "timestamp": ts,
            }
        except Exception as e:
            logger.error("failed to create registration request: %s", e)
            return None

    # ---------- Client token persistence ----------

    def save_client_token(self, token: str) -> bool:
        try:
            self.auth_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.token_file.write_text(token)
            self.token_file.chmod(0o600)
            return True
        except Exception as e:
            logger.error("failed to save client token: %s", e)
            return False

    def load_client_token(self) -> Optional[str]:
        try:
            if self.token_file.exists():
                return self.token_file.read_text().strip()
            return None
        except Exception as e:
            logger.error("failed to load client token: %s", e)
            return None


def setup_client_auth(auth_dir: Path = Path("/etc/dcmon"), force_regenerate: bool = False) -> Optional[ClientAuth]:
    """
    Ensure keys exist and return a ClientAuth instance.

    - If keys missing or force_regenerate=True, generate new keypair.
    - Does not contact the server or perform registration.
    """
    if not CRYPTO_AVAILABLE:
        logger.error("cryptography package is required (pip install cryptography)")
        return None

    try:
        auth = ClientAuth(auth_dir)
        if not auth.has_valid_keys() or force_regenerate:
            if not auth.generate_key_pair():
                return None
        return auth
    except Exception as e:
        logger.error("failed to set up client auth: %s", e)
        return None


if __name__ == "__main__":
    # Simple CLI helper for local testing
    import argparse, json as _json, socket

    parser = argparse.ArgumentParser(description="dcmon client auth helper")
    parser.add_argument("--auth-dir", default="/etc/dcmon", dest="auth_dir",
                        help="directory for client credentials (private key, public key, client token)")
    parser.add_argument("--gen-keys", action="store_true", help="generate a new RSA keypair")
    parser.add_argument("--registration", action="store_true", help="print a registration request JSON")
    parser.add_argument("--hostname", default=socket.gethostname(), help="hostname to include in challenge")
    args = parser.parse_args()

    auth = setup_client_auth(Path(args.auth_dir), force_regenerate=args.gen_keys)
    if not auth:
        raise SystemExit(1)

    if args.registration:
        req = auth.create_registration_request(args.hostname)
        if not req:
            raise SystemExit(2)
        print(_json.dumps(req, indent=2))
    else:
        print(f"Keys OK in {args.auth_dir}. Use --registration to print a request.")
