#!/usr/bin/env python3
"""
dcmon client

Flow:
- Credentials live under --auth-dir (default /etc/dcmon): client.key, client.pub, client_token
- If client_token is missing:
    * ensure keys exist (generate if needed)
    * prompt for admin token (secure input, not stored)
    * register with server using admin token + cryptographic proof
    * save returned client_token for future use
- If client_token exists:
    * collect lightweight system metrics (no external deps)
    * POST /api/metrics with Authorization: Bearer <client_token>
    * loop every --interval seconds (or --once for a single send)

Admin token is only used during initial registration and never stored on client.
"""

import argparse
import asyncio
import getpass
import json
import logging
import os
import socket
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Local auth helper (keys + registration request)
try:
    # when run as module
    from .auth import ClientAuth, setup_client_auth
    from .exporters import OSMetricsExporter, IpmiExporter, AptExporter, NvmeExporter, NvsmiExporter
except ImportError:
    # when run as script from project root
    from auth import ClientAuth, setup_client_auth
    from exporters import OSMetricsExporter, IpmiExporter, AptExporter, NvmeExporter, NvsmiExporter


LOG = logging.getLogger("dcmon.client")


# ---------------- HTTP helpers ----------------

def _post_json(url: str, data: Dict[str, Any], headers: Dict[str, str], timeout: int = 10) -> Dict[str, Any]:
    body = json.dumps(data).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = Request(url, data=body, headers=hdrs, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


# ---------------- Registration UX ----------------

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


# ---------------- Metrics collection (stdlib only) ----------------

def _now() -> int:
    return int(time.time())


async def collect_metrics(hostname: str) -> List[Dict[str, Any]]:
    """
    Collect metrics from all available exporters.
    Returns metrics in server's expected schema format.
    """
    all_metrics = []
    
    # Initialize all exporters
    exporters = [
        OSMetricsExporter(),
        IpmiExporter(),
        AptExporter(), 
        NvmeExporter(),
        NvsmiExporter(),
    ]
    
    # Collect from each exporter
    for exporter in exporters:
        try:
            exporter_metrics = await exporter.collect()
            # Convert MetricPoint objects to dict format expected by server
            for metric in exporter_metrics:
                # Determine value type from MetricPoint's integer classification
                value_type = "int" if isinstance(metric.value, int) else "float"
                
                metric_dict = {
                    "timestamp": metric.timestamp,
                    "metric_name": metric.name,
                    "labels": metric.labels,
                    "value_type": value_type,
                    "value": float(metric.value)  # Always send as float, server will convert if needed
                }
                    
                all_metrics.append(metric_dict)
                
        except Exception as e:
            LOG.warning(f"Failed to collect metrics from {exporter.__class__.__name__}: {e}")
            continue
    
    return all_metrics


def send_metrics(server_base: str, client_token: str, metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not metrics:
        return {"received": 0, "inserted": 0}
    url = server_base.rstrip("/") + "/api/metrics"
    headers = {"Authorization": f"Bearer {client_token}"}
    return _post_json(url, {"metrics": metrics}, headers)


def register_client_interactively(auth: ClientAuth, server_base: str, hostname: str) -> str:
    """
    Prompt for admin token and register client with server.
    Returns client_token on success, raises SystemExit on failure.
    """
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
    
    # Add admin token to request (only in memory)
    req["admin_token"] = admin_token
    
    # Send registration request
    url = server_base.rstrip("/") + "/api/clients/register"
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    try:
        response = _post_json(url, req, headers)
        client_token = response.get("client_token")
        if not client_token:
            raise SystemExit("ERROR: Server did not return client_token in registration response.")
        
        print("✅ Client registered successfully!")
        LOG.info("Client registered with server: %s", server_base)
        return client_token
        
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


# ---------------- Main ----------------

async def run_client(auth_dir: Path, server: str, interval: int, once: bool, registration_only: bool) -> None:
    # Configure auth helper (keys + token)
    auth = setup_client_auth(auth_dir)
    if not auth:
        raise SystemExit(1)

    # Registration-only mode: print request JSON to stdout and exit
    if registration_only:
        req = auth.create_registration_request(socket.gethostname())
        if not req:
            raise SystemExit("ERROR: failed to create registration request.")
        print(json.dumps(req, indent=2))
        return

    # Ensure client token exists; otherwise register interactively
    token = auth.load_client_token()
    if not token:
        hostname = socket.gethostname()
        # Interactive registration with admin token prompt
        token = register_client_interactively(auth, server, hostname)
        # Save the client token for future use
        if not auth.save_client_token(token):
            raise SystemExit("ERROR: Failed to save client token after registration.")
        LOG.info("Client token saved successfully")

    # Metrics loop
    LOG.info("client starting; posting metrics to %s every %ss", server, interval)
    while True:
        try:
            batch = await collect_metrics(socket.gethostname())
            if not batch:
                LOG.warning("no metrics collected")
            res = send_metrics(server, token, batch)
            LOG.debug("sent metrics: %s", res)
        except HTTPError as e:
            try:
                msg = e.read().decode("utf-8")
            except Exception:
                msg = str(e)
            LOG.error("HTTP %s error from server: %s", getattr(e, "code", "?"), msg)
        except URLError as e:
            LOG.error("failed to reach server: %s", e)
        except Exception as e:
            LOG.exception("unexpected error during metrics send: %s", e)

        if once:
            break
        await asyncio.sleep(max(1, interval))


def main():
    parser = argparse.ArgumentParser(description="dcmon client")
    parser.add_argument("--auth-dir", default="/etc/dcmon", dest="auth_dir",
                        help="directory for client credentials (private key, public key, client token)")
    parser.add_argument("--server", default="http://127.0.0.1:8000",
                        help="dcmon server base URL (e.g., http://server:8000)")
    parser.add_argument("--interval", type=int, default=30,
                        help="seconds between metric posts")
    parser.add_argument("--once", action="store_true",
                        help="send one metrics batch and exit")
    parser.add_argument("--registration", action="store_true",
                        help="print a registration request JSON to stdout and exit")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="logging level")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level))

    try:
        asyncio.run(run_client(
            auth_dir=Path(args.auth_dir),
            server=args.server,
            interval=args.interval,
            once=args.once,
            registration_only=args.registration,
        ))
    except KeyboardInterrupt:
        print("\nInterrupted. Bye!")


if __name__ == "__main__":
    main()
