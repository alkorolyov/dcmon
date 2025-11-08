"""
Client registration utilities for dcmon.

Handles the registration workflow including:
- Creating registration requests
- Interactive admin token prompt
- Communicating with server for registration
- Displaying registration instructions
"""

import base64
import getpass
import json
import logging
from pathlib import Path
from typing import Dict, Tuple
from urllib.error import HTTPError, URLError

# Local imports (handle both module and script execution)
try:
    # when run as module
    from .auth import ClientAuth
    from .hardware import detect_hardware, detect_vast_machine_id, detect_vast_port_range
    from .http_client import DCMonHttpClient
except ImportError:
    # when run as script from project root
    from auth import ClientAuth
    from hardware import detect_hardware, detect_vast_machine_id, detect_vast_port_range
    from http_client import DCMonHttpClient


logger = logging.getLogger(__name__)


def ensure_registration_request(auth: ClientAuth, auth_dir: Path, hostname: str) -> Path:
    """
    Create <auth_dir>/registration_request.json with the signed request and return its path.
    """
    req = auth.create_registration_request(hostname=hostname)
    if not req:
        raise SystemExit("ERROR: failed to create registration request (keys missing or crypto error).")
    out_path = auth_dir / "registration_request.json"
    out_path.write_text(json.dumps(req, indent=2))
    try:
        out_path.chmod(0o600)
    except Exception:
        pass
    return out_path


def print_registration_instructions(server_base: str, req_path: Path, auth_dir: Path):
    """Print manual registration instructions for admin."""
    server_base = server_base.rstrip("/")
    print(
        f"\n⚠️  No client token found in {auth_dir}.\n"
        f"   A registration request has been written to:\n"
        f"     {req_path}\n\n"
        f"➜ Ask an administrator to register this client:\n"
        f"   curl -X POST {server_base}/api/clients/register \\\n"
        f"        -H \"Authorization: Bearer <ADMIN_TOKEN>\" \\\n"
        f"        -H \"Content-Type: application/json\" \\\n"
        f"        --data-binary @{req_path}\n\n"
        f"   The server will return JSON with a client_token. Save it to:\n"
        f"     {auth_dir}/client_token    (chmod 600)\n\n"
        f"   Then re-run this client.\n"
    )


def register_client_interactively(
    auth: ClientAuth,
    server_base: str,
    hostname: str,
    test_mode: bool = False
) -> Tuple[str, int]:
    """
    Register client with server using admin authentication.

    In test mode, automatically uses dev token. In production, prompts for admin token.

    Args:
        auth: ClientAuth instance with keys
        server_base: Server base URL
        hostname: Client hostname
        test_mode: If True, use dev admin token without prompting

    Returns:
        (client_token, client_id) on success

    Raises:
        SystemExit: On registration failure
    """
    if test_mode:
        print(f"\n🔧 Test mode detected - using dev admin token for registration of {hostname}")
        admin_token = "dev_admin_token_12345"
    else:
        print(f"\n🔐 Client registration required for {hostname}")
        print("Please enter the admin token to register this client with the server.")

        try:
            admin_token = getpass.getpass("Admin token: ").strip()
        except (EOFError, KeyboardInterrupt):
            # Fallback for non-interactive environments (testing/IDE)
            print("\nFallback to regular input (dev mode):")
            admin_token = input("Admin token: ").strip()

        if not admin_token:
            raise SystemExit("ERROR: Admin token cannot be empty.")

    # Create registration request
    req = auth.create_registration_request(hostname=hostname)
    if not req:
        raise SystemExit("ERROR: Failed to create registration request (keys missing or crypto error).")

    # Detect hardware information
    print("🔍 Detecting hardware specifications...")
    hardware = detect_hardware()

    # Add hardware info to registration request
    req.update(hardware)

    # Detect Vast.ai information if available
    vast_machine_id = detect_vast_machine_id()
    vast_port_range = detect_vast_port_range()
    if vast_machine_id:
        req["vast_machine_id"] = vast_machine_id
    if vast_port_range:
        req["vast_port_range"] = vast_port_range

    # Add admin token to request (only in memory)
    req["admin_token"] = admin_token

    # Create HTTP client and send registration request using Basic Auth
    http_client = DCMonHttpClient(server_base)
    credentials = base64.b64encode(f"admin:{admin_token}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}"}

    try:
        response = http_client.post_json("/api/clients/register", req, headers)
        client_token = response.get("client_token")
        client_id = response.get("client_id")

        if not client_token:
            raise SystemExit("ERROR: Server did not return client_token in registration response.")
        if not client_id:
            raise SystemExit("ERROR: Server did not return client_id in registration response.")

        print("✅ Client registered successfully!")
        logger.info("Client registered with server: %s (client_id=%s)", server_base, client_id)
        return client_token, client_id

    except HTTPError as e:
        try:
            error_msg = e.read().decode("utf-8")
        except Exception:
            error_msg = str(e)
        raise SystemExit(f"ERROR: Registration failed (HTTP {getattr(e, 'code', '?')}): {error_msg}")

    except URLError as e:
        raise SystemExit(f"ERROR: Failed to reach server: {e}")

    except Exception as e:
        raise SystemExit(f"ERROR: Registration failed: {e}")
