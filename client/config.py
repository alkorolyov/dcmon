import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any

import yaml

from client.client import logger


@dataclass
class ClientConfig:
    """Client configuration with defaults"""
    auth_dir: str = "/etc/dcmon"
    server: str = "https://127.0.0.1:8000"
    interval: int = 30
    log_level: str = "INFO"
    once: bool = False
    registration: bool = False
    test_mode: bool = False
    exporters: Dict[str, Any] = None
    os_metrics: Dict[str, Any] = None
    log_monitoring: Dict[str, Any] = None

    def __post_init__(self):
        # Metrics exporters configuration (enable/disable)
        if self.exporters is None:
            self.exporters = {
                "os": True,
                "ipmi": True,
                "apt": True,
                "nvme": True,
                "nvsmi": True,
                "bmc_fan": True,
                "ipmicfg_psu": True
            }

        # OS metrics specific configuration
        if self.os_metrics is None:
            self.os_metrics = {
                "mountpoints": ["/", "/var/lib/docker"]
            }

        # Log monitoring configuration
        if self.log_monitoring is None:
            self.log_monitoring = {
                "enabled": False,
                "sources": ["dmesg", "journal"],
                "severity_filter": "ERROR",
                "max_lines_per_cycle": 25,
                "history_size": 1000  # Number of historical entries on first run
            }

    @classmethod
    def from_file(cls, config_path: Path) -> "ClientConfig":
        """Load configuration from YAML file"""
        if not config_path.exists():
            logger.debug(f"Config file not found: {config_path}, using defaults")
            return cls()

        try:
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
            logger.debug(f"Loaded config from {config_path}: {data}")
            return cls(**data)
        except Exception as e:
            logger.warning(f"Failed to load config from {config_path}: {e}, using defaults")
            return cls()

    def override_with_args(self, args: argparse.Namespace) -> "ClientConfig":
        """Override config with command line arguments if provided"""
        # Only override if explicitly provided - preserves config file values
        self.auth_dir = args.auth_dir if args.auth_dir is not None else self.auth_dir
        self.server = args.server if args.server is not None else self.server
        self.interval = args.interval if args.interval is not None else self.interval
        self.log_level = args.log_level if args.log_level is not None else self.log_level
        self.once = args.once
        self.registration = args.registration
        return self
