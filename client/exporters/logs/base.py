import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List


@dataclass
class LogEntry:
    """Represents a collected log entry"""
    log_source: str  # 'dmesg', 'journal', 'syslog'
    log_timestamp: int
    content: str
    severity: Optional[str] = None



class LogExporter:
    """Base class for log exporters with common functionality."""

    def __init__(self, auth_dir: Path, config: Optional[Dict] = None):
        self.auth_dir = Path(auth_dir)
        self.cursors_file = self.auth_dir / "log-cursors.json"
        self.config = config or {}
        self.logger = logging.getLogger(f"dcmon.{self.__class__.__name__.lower()}")

        # Configuration
        log_config = self.config.get('log_monitoring', {})
        self.enabled = log_config.get('enabled', False)
        self.max_lines_per_cycle = log_config.get('max_lines_per_cycle', 50)
        self.severity_filter = log_config.get('severity_filter', 'WARN')
        self.enabled_sources = log_config.get('sources', ['dmesg', 'journal'])
        self.history_size = log_config.get('history_size', 1000)

        # Each exporter has a source_name (defined in children)
        self.source_name = getattr(self, 'source_name', 'unknown')

    def is_enabled(self) -> bool:
        """Check if this log source is enabled and available."""
        return (self.enabled and
                self.source_name in self.enabled_sources and
                self.is_available())

    def get_cursor_key(self) -> str:
        """Get the cursor key for this exporter."""
        return self.source_name

    @staticmethod
    def _parse_severity(line: str) -> str:
        """Parse severity level from log line."""
        line_lower = line.lower()
        if any(word in line_lower for word in ['error', 'err', 'fatal', 'fail', 'critical']):
            return 'ERROR'
        elif any(word in line_lower for word in ['warn', 'warning']):
            return 'WARN'
        elif any(word in line_lower for word in ['debug']):
            return 'DEBUG'
        else:
            return 'INFO'  # Default to INFO for all unrecognized patterns

    def _should_include_severity(self, severity: str) -> bool:
        """Check if severity should be included based on filter."""
        severity_levels = {'DEBUG': 0, 'INFO': 1, 'WARN': 2, 'ERROR': 3}
        filter_level = severity_levels.get(self.severity_filter, 2)
        entry_level = severity_levels.get(severity, 0)
        return entry_level >= filter_level

    # Abstract methods to be implemented by children
    def is_available(self) -> bool:
        """Check if the log source is available."""
        raise NotImplementedError("Subclasses must implement is_available()")

    def collect_incremental(self, cursors: Dict) -> List[LogEntry]:
        """Collect new log entries since last cursor position."""
        raise NotImplementedError("Subclasses must implement collect_incremental()")

    def collect_history(self, cursors: Dict) -> List[LogEntry]:
        """Collect historical log entries (first run)."""
        raise NotImplementedError("Subclasses must implement collect_history()")

    def update_cursor(self, cursors: Dict, **cursor_data) -> None:
        """Update cursor data for this log source."""
        cursors[self.source_name] = cursor_data
