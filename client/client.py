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
import json
import logging
import socket
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.error import HTTPError, URLError

# Local imports (handle both module and script execution)
try:
    # when run as module
    from .config import ClientConfig
    from .auth import setup_client_auth
    from .exporters import MetricsCollectorManager, LogExporterManager
    from .commands import start_websocket_command_client
    from .hardware import detect_hardware
    from .http_client import DCMonHttpClient
    from .registration import register_client_interactively
except ImportError:
    # when run as script from project root
    from config import ClientConfig
    from auth import setup_client_auth
    from exporters import MetricsCollectorManager, LogExporterManager
    from commands import start_websocket_command_client
    from hardware import detect_hardware
    from http_client import DCMonHttpClient
    from registration import register_client_interactively


logger = logging.getLogger(__name__)


# ---------------- Main ----------------

async def metrics_loop(
    config: ClientConfig,
    token: str,
    hw_hash: Optional[str],
    metrics_collector: MetricsCollectorManager,
    log_exporter: LogExporterManager
) -> None:
    """Main metrics collection loop."""
    logger.info("metrics loop starting; posting to %s every %ss", config.server, config.interval)
    connection_failed = False
    http_client = DCMonHttpClient(config.server)

    while True:
        try:
            batch = await metrics_collector.collect_metrics()
            if not batch:
                logger.warning("no metrics collected")

            # Collect logs (non-async, synchronous collection)
            log_entries = log_exporter.collect_new_logs()
            logs_data = []
            if log_entries:
                logs_data = [
                    {
                        "log_source": entry.log_source,
                        "log_timestamp": entry.log_timestamp,
                        "content": entry.content,
                        "severity": entry.severity
                    }
                    for entry in log_entries
                ]

            res = http_client.send_metrics(token, batch, hw_hash, logs_data if logs_data else None)
            logger.debug("sent metrics: %s", res)

            # Log successful reconnection after failures
            if connection_failed:
                logger.info("successfully reconnected to server: %s", config.server)
                connection_failed = False

        except HTTPError as e:
            connection_failed = True
            try:
                msg = e.read().decode("utf-8")
            except Exception:
                msg = str(e)
            logger.error("HTTP %s error from server: %s", getattr(e, "code", "?"), msg)
        except URLError as e:
            connection_failed = True
            logger.error("failed to reach server: %s", e)
        except Exception as e:
            connection_failed = True
            logger.exception("unexpected error during metrics send: %s", e)

        if config.once:
            break
        await asyncio.sleep(max(1, config.interval))


async def run_client(config: ClientConfig) -> None:
    """Main client orchestration."""
    # Configure auth helper (keys + token)
    auth_dir = Path(config.auth_dir)
    auth = setup_client_auth(auth_dir)
    if not auth:
        raise SystemExit(1)

    # Registration-only mode: print request JSON to stdout and exit
    if config.registration:
        req = auth.create_registration_request(socket.gethostname())
        if not req:
            raise SystemExit("ERROR: failed to create registration request.")
        print(json.dumps(req, indent=2))
        return

    # Ensure client token and ID exist; otherwise register interactively
    token = auth.load_client_token()
    client_id = auth.load_client_id()

    if not token or not client_id:
        hostname = socket.gethostname()
        # Interactive registration with admin token prompt
        token, client_id = register_client_interactively(auth, config.server, hostname, config.test_mode)
        # Save the client token and ID for future use
        if not auth.save_client_token(token):
            raise SystemExit("ERROR: Failed to save client token after registration.")
        if not auth.save_client_id(client_id):
            raise SystemExit("ERROR: Failed to save client ID after registration.")
        logger.info("Client token and ID saved successfully")

    # Generate hardware hash once for metrics sending
    hw_info = detect_hardware()
    hw_hash = hw_info.get("hw_hash")

    # Initialize metrics collector once (singleton exporters) with hardware info and config
    metrics_collector = MetricsCollectorManager(hw_info=hw_info, config=config.__dict__)

    # Initialize log exporter manager with auth_dir and config
    log_exporter = LogExporterManager(Path(config.auth_dir), config.__dict__)

    # Start both metrics collection and WebSocket command server concurrently
    logger.info("starting dcmon client with metrics collection and WebSocket commands")

    if config.once:
        # For --once mode, only run metrics
        await metrics_loop(config, token, hw_hash, metrics_collector, log_exporter)
    else:
        # Run both metrics and WebSocket command client concurrently
        await asyncio.gather(
            metrics_loop(config, token, hw_hash, metrics_collector, log_exporter),
            start_websocket_command_client(config, client_id, token)
        )


def main():
    parser = argparse.ArgumentParser(description="dcmon client")
    parser.add_argument("--config", "-c", type=Path, default=Path("config.yml"),
                        help="YAML configuration file (default: config.yml)")
    parser.add_argument("--auth-dir", dest="auth_dir",
                        help="directory for client credentials (private key, public key, client token)")
    parser.add_argument("--server",
                        help="dcmon server base URL (e.g., https://server:8000)")
    parser.add_argument("--interval", type=int,
                        help="seconds between metric posts")
    parser.add_argument("--once", action="store_true",
                        help="send one metrics batch and exit")
    parser.add_argument("--registration", action="store_true",
                        help="print a registration request JSON to stdout and exit")
    parser.add_argument("--log-level",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="logging level")
    args = parser.parse_args()

    # Load config: YAML first, then CLI overrides
    config = ClientConfig.from_file(args.config).override_with_args(args)
    
    # Configure logging
    logging.basicConfig(level=getattr(logging, config.log_level))
    logger.info(f"dcmon client starting with config: server={config.server}, interval={config.interval}s")

    try:
        asyncio.run(run_client(config))
    except KeyboardInterrupt:
        print("\nInterrupted. Bye!")


if __name__ == "__main__":
    main()
