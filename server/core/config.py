#!/usr/bin/env python3
"""
dcmon Server Configuration Management

Policy (no paths in config):
- PROD (test_mode: false)
    DB:         /var/lib/dcmon-server/dcmon.db
    Admin token:/etc/dcmon-server/admin_token  (must exist; else startup fails)
- DEV  (test_mode: true)
    DB:         ./dcmon.db
    Admin token:./admin_token  (if missing, generate ephemeral and log)
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

import yaml
from pydantic import BaseModel

logger = logging.getLogger("dcmon.server")


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    metrics_days: int = 7
    logs_days: int = 7
    # File paths - explicit configuration
    auth_dir: str
    db_path: str
    # Behavior controls
    test_mode: bool = False          # Only controls admin token fallback
    use_tls: bool = False           # Controls HTTPS on/off


def load_config_from(path: str) -> ServerConfig:
    """Load server configuration from YAML file."""
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    return ServerConfig(**data)


def resolve_paths(cfg: ServerConfig) -> Tuple[Path, Path, bool, Path, Path]:
    """
    Return (db_path, admin_token_path, allow_ephemeral_admin_token, cert_path, key_path)
    based on explicit config paths.
    """
    auth_dir = Path(cfg.auth_dir)
    
    return (
        Path(cfg.db_path),                    # Database at explicit path
        auth_dir / "admin_token",             # Admin token in auth_dir
        cfg.test_mode,                        # Only controls admin token fallback
        auth_dir / "server.crt",              # Certificate in auth_dir
        auth_dir / "server.key"               # Private key in auth_dir
    )


def read_admin_token(path: Path) -> Optional[str]:
    """Read admin token from file, return None if not readable."""
    try:
        with open(path, "r") as f:
            tok = f.read().strip()
            return tok or None
    except Exception as e:
        logger.debug("admin token file not readable (%s): %s", path, e)
        return None