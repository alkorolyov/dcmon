"""Vast.ai log exporter for /var/lib/vastai_kaalia/kaalia.log."""

import time
from pathlib import Path
from typing import Dict, List, Optional

from .base import LogEntry, LogExporter


class VastLogExporter(LogExporter):
    """Vast.ai log exporter for /var/lib/vastai_kaalia/kaalia.log."""

    source_name = "vast"

    def is_available(self) -> bool:
        """Check if vast log file exists."""
        return Path('/var/lib/vastai_kaalia/kaalia.log').exists()

    def collect_incremental(self, cursors: Dict) -> List[LogEntry]:
        """Collect new vast log entries using file position tracking."""
        try:
            vast_file = Path('/var/lib/vastai_kaalia/kaalia.log')
            if not vast_file.exists():
                return []

            # Handle missing cursor (first run for this log source)
            if self.source_name not in cursors:
                return self.collect_history(cursors)

            cursor = cursors[self.source_name]
            stat = vast_file.stat()

            # Check for log rotation (inode changed)
            if cursor['inode'] != 0 and cursor['inode'] != stat.st_ino:
                cursor['byte_offset'] = 0
                cursor['inode'] = stat.st_ino

            # Read new content
            with open(vast_file, 'r') as f:
                f.seek(cursor['byte_offset'])
                new_content = f.read()
                new_offset = f.tell()

            if not new_content.strip():
                return []

            entries = []
            for line in new_content.strip().split('\n'):
                if not line.strip():
                    continue

                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue

                parsed_timestamp = self._parse_vast_timestamp(line)
                if parsed_timestamp is None:
                    continue

                entries.append(LogEntry(
                    log_source=self.source_name,
                    log_timestamp=parsed_timestamp,
                    content=self._strip_vast_metadata(line),
                    severity=severity
                ))

            # Update cursor
            self.update_cursor(cursors,
                              byte_offset=new_offset,
                              inode=stat.st_ino,
                              last_timestamp=int(time.time()))

            return entries

        except Exception as e:
            raise Exception(f"Failed to collect vast incremental: {e}")

    def collect_history(self, cursors: Dict) -> List[LogEntry]:
        """Collect last 1000 lines from vast log file (first run)."""
        try:
            vast_file = Path('/var/lib/vastai_kaalia/kaalia.log')
            if not vast_file.exists():
                raise Exception("/var/lib/vastai_kaalia/kaalia.log does not exist")

            # Read last 1000 lines from file
            with open(vast_file, 'r') as f:
                lines = f.readlines()

            # Crop to last 1000 lines
            if len(lines) > 1000:
                lines = lines[-1000:]
                self.logger.info(f"vast history cropped to last 1000 lines")

            entries = []
            for line in lines:
                if not line.strip():
                    continue

                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue

                parsed_timestamp = self._parse_vast_timestamp(line)
                if parsed_timestamp is None:
                    continue

                entries.append(LogEntry(
                    log_source=self.source_name,
                    log_timestamp=parsed_timestamp,
                    content=self._strip_vast_metadata(line),
                    severity=severity
                ))

            # Set cursor for future incremental collection
            stat = vast_file.stat()
            self.update_cursor(cursors,
                              byte_offset=stat.st_size,
                              inode=stat.st_ino,
                              last_timestamp=int(time.time()))

            return entries

        except Exception as e:
            raise Exception(f"Failed to collect vast history: {e}")

    def _parse_vast_timestamp(self, line: str) -> Optional[int]:
        """Parse vast timestamp from format '[2025-09-07 15:33:07.798]' and convert to UTC."""
        import re
        from datetime import datetime, timezone
        try:
            match = re.match(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]', line.strip())
            if not match:
                return None

            timestamp_str = match.group(1)
            dt_local = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
            dt_local = dt_local.replace(tzinfo=datetime.now().astimezone().tzinfo)
            return int(dt_local.astimezone(timezone.utc).timestamp())
        except Exception as e:
            raise Exception(f"Failed to parse vast timestamp from '{line[:50]}...': {e}")

    def _strip_vast_metadata(self, line: str) -> str:
        """Strip timestamp and metadata from vast line, keeping only message content."""
        import re
        match = re.match(r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] \[Kaalia\] \[(?:info|warn|error)\] P\d+\s+(.*)', line.strip())
        if match:
            return match.group(1)
        return line.strip()
