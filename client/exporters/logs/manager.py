"""Log Exporter Manager - Coordinates all log collection"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from .base import LogEntry
from .journal import JournalExporter
from .dmesg import DmesgExporter
from .syslog import SyslogExporter
from .vast import VastLogExporter


class LogExporterManager:
    """Manages all log exporters and coordinates log collection."""

    # Registry mapping source names to exporter classes
    EXPORTER_REGISTRY = {
        "journal": JournalExporter,
        "dmesg": DmesgExporter,
        "syslog": SyslogExporter,
        "vast": VastLogExporter,
    }

    def __init__(self, auth_dir: Path, config: Optional[Dict] = None):
        """
        Initialize log exporter manager based on configuration.

        Args:
            auth_dir: Directory containing client authentication and cursor state
            config: Configuration dictionary (typically from client config)
        """
        self.auth_dir = Path(auth_dir)
        self.config = config or {}
        self.cursors_file = self.auth_dir / "log-cursors.json"
        self.logger = logging.getLogger("dcmon.log_exporter_manager")

        # Get log monitoring configuration
        log_config = self.config.get("log_monitoring", {})
        enabled_sources = log_config.get("sources", [])

        self.logger.info("Initializing log exporters from config...")
        self.exporters = []

        # Instantiate only enabled log exporters
        for source_name, exporter_class in self.EXPORTER_REGISTRY.items():
            # Check if this source is in the enabled sources list
            if source_name not in enabled_sources:
                self.logger.debug(f"Skipping disabled log source: {source_name}")
                continue

            try:
                exporter = exporter_class(auth_dir, config)

                # Only add if available
                if exporter.is_available():
                    self.exporters.append(exporter)
                    self.logger.info(f"Enabled log exporter: {source_name}")
                else:
                    self.logger.debug(f"Log exporter {source_name} not available on this system")

            except Exception as e:
                self.logger.warning(f"Failed to initialize log exporter {source_name}: {e}")
                continue

        self.logger.info(f"Initialized {len(self.exporters)} log exporters")

    def _load_cursors(self) -> Dict:
        """Load cursor state from file."""
        if not self.cursors_file.exists():
            return {}

        try:
            with open(self.cursors_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.warning(f"Failed to load cursors from {self.cursors_file}: {e}")
            return {}

    def _save_cursors(self, cursors: Dict) -> None:
        """Save cursor state to file."""
        try:
            self.cursors_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cursors_file, 'w') as f:
                json.dump(cursors, f, indent=2)
        except IOError as e:
            self.logger.error(f"Failed to save cursors to {self.cursors_file}: {e}")

    def collect_new_logs(self) -> List[LogEntry]:
        """
        Collect new log entries from all enabled exporters.

        Returns:
            List of LogEntry objects from all sources
        """
        all_logs = []
        cursors = self._load_cursors()

        for exporter in self.exporters:
            # Skip if exporter is not enabled
            if not exporter.is_enabled():
                continue

            try:
                # Check if this is first run (no cursor for this source)
                cursor_key = exporter.get_cursor_key()
                is_first_run = cursor_key not in cursors

                if is_first_run:
                    # First run: collect history (limited)
                    logs = exporter.collect_history(cursors)
                    self.logger.info(f"{exporter.source_name}: first run, collected {len(logs)} historical entries")
                else:
                    # Incremental collection
                    logs = exporter.collect_incremental(cursors)
                    if logs:
                        self.logger.debug(f"{exporter.source_name}: collected {len(logs)} new entries")

                all_logs.extend(logs)

            except Exception as e:
                self.logger.error(f"Failed to collect logs from {exporter.source_name}: {e}")
                continue

        # Save updated cursors
        if cursors:
            self._save_cursors(cursors)

        return all_logs
