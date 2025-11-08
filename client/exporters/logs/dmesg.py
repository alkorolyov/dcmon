"""Kernel dmesg exporter."""

import time
from pathlib import Path
from typing import Dict, List, Optional

from .base import LogEntry, LogExporter


class DmesgExporter(LogExporter):
    """Kernel dmesg exporter."""

    source_name = "dmesg"

    def __init__(self, auth_dir: Path, config: Optional[Dict] = None):
        super().__init__(auth_dir, config)
        # Cache boot time once - only changes on system reboot (which restarts client)
        self.boot_time = self._get_boot_time() if self.is_enabled() else None

    def is_available(self) -> bool:
        """dmesg is always available on Linux systems."""
        return True

    def collect_incremental(self, cursors: Dict) -> List[LogEntry]:
        """Collect new dmesg entries using line count tracking."""
        try:
            import subprocess

            # Handle missing cursor (first run for this log source)
            if self.source_name not in cursors:
                return self.collect_history(cursors)

            cursor = cursors[self.source_name]

            # Get current dmesg output
            result = subprocess.run(['dmesg'], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise Exception(f"dmesg command failed: {result.stderr}")

            lines = result.stdout.strip().split('\n')
            last_line = cursor.get('last_line', 0)

            # Get new lines
            if len(lines) <= last_line:
                return []

            new_lines = lines[last_line:]
            entries = []

            for line in new_lines:
                if not line.strip():
                    continue

                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue

                parsed_timestamp = self._parse_dmesg_timestamp(line)
                if parsed_timestamp is None:
                    continue

                entries.append(LogEntry(
                    log_source=self.source_name,
                    log_timestamp=parsed_timestamp,
                    content=line.strip(),
                    severity=severity
                ))

            # Update cursor
            self.update_cursor(cursors,
                              last_line=len(lines),
                              last_timestamp=int(time.time()))

            return entries

        except Exception as e:
            raise Exception(f"Failed to collect dmesg incremental: {e}")

    def collect_history(self, cursors: Dict) -> List[LogEntry]:
        """Collect full dmesg history since boot (first run)."""
        try:
            import subprocess

            result = subprocess.run(['dmesg'], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise Exception(f"dmesg command failed: {result.stderr}")

            lines = result.stdout.strip().split('\n')

            # Crop to last 1000 lines if exceeding
            if len(lines) > 1000:
                lines = lines[-1000:]
                self.logger.info(f"dmesg history cropped to last 1000 lines")

            entries = []
            for line in lines:
                if not line.strip():
                    continue

                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue

                parsed_timestamp = self._parse_dmesg_timestamp(line)
                if parsed_timestamp is None:
                    continue

                entries.append(LogEntry(
                    log_source=self.source_name,
                    log_timestamp=parsed_timestamp,
                    content=line.strip(),
                    severity=severity
                ))

            # Set cursor to total line count for future incremental collection
            self.update_cursor(cursors,
                              last_line=len(result.stdout.strip().split('\n')),
                              last_timestamp=int(time.time()))

            return entries

        except Exception as e:
            raise Exception(f"Failed to collect dmesg history: {e}")

    def _get_boot_time(self) -> int:
        """Get system boot time from /proc/stat."""
        try:
            with open('/proc/stat', 'r') as f:
                for line in f:
                    if line.startswith('btime'):
                        return int(line.split()[1])
            raise Exception("btime not found in /proc/stat")
        except Exception as e:
            raise Exception(f"Failed to get boot time: {e}")

    def _parse_dmesg_timestamp(self, line: str) -> Optional[int]:
        """Parse dmesg timestamp from kernel line format [12345.67]."""
        import re
        try:
            match = re.match(r'^\[\s*(\d+\.\d+)\]', line.strip())
            if not match:
                return None

            kernel_seconds = float(match.group(1))
            return self.boot_time + int(kernel_seconds)
        except Exception as e:
            raise Exception(f"Failed to parse dmesg timestamp from '{line[:50]}...': {e}")
