"""System syslog exporter for /var/log/syslog."""

import time
from pathlib import Path
from typing import Dict, List, Optional

from .base import LogEntry, LogExporter


class SyslogExporter(LogExporter):
    """System syslog exporter for /var/log/syslog."""

    source_name = "syslog"

    def is_available(self) -> bool:
        """Check if syslog file exists."""
        return Path('/var/log/syslog').exists()

    def collect_incremental(self, cursors: Dict) -> List[LogEntry]:
        """Collect new syslog entries using file position tracking."""
        try:
            syslog_file = Path('/var/log/syslog')
            if not syslog_file.exists():
                return []

            # Handle missing cursor (first run for this log source)
            if self.source_name not in cursors:
                return self.collect_history(cursors)

            cursor = cursors[self.source_name]
            stat = syslog_file.stat()

            # Check for log rotation (inode changed)
            if cursor['inode'] != 0 and cursor['inode'] != stat.st_ino:
                cursor['byte_offset'] = 0
                cursor['inode'] = stat.st_ino

            # Read new content
            with open(syslog_file, 'r') as f:
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

                parsed_timestamp = self._parse_syslog_timestamp(line)
                if parsed_timestamp is None:
                    continue

                entries.append(LogEntry(
                    log_source=self.source_name,
                    log_timestamp=parsed_timestamp,
                    content=self._strip_syslog_timestamp(line),
                    severity=severity
                ))

            # Update cursor
            self.update_cursor(cursors,
                              byte_offset=new_offset,
                              inode=stat.st_ino,
                              last_timestamp=int(time.time()))

            return entries

        except Exception as e:
            raise Exception(f"Failed to collect syslog incremental: {e}")

    def collect_history(self, cursors: Dict) -> List[LogEntry]:
        """Collect last 1000 lines from syslog file (first run)."""
        try:
            syslog_file = Path('/var/log/syslog')
            if not syslog_file.exists():
                raise Exception("/var/log/syslog does not exist")

            # Read last 1000 lines from file
            with open(syslog_file, 'r') as f:
                lines = f.readlines()

            # Crop to last 1000 lines
            if len(lines) > 1000:
                lines = lines[-1000:]
                self.logger.info(f"syslog history cropped to last 1000 lines")

            entries = []
            for line in lines:
                if not line.strip():
                    continue

                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue

                parsed_timestamp = self._parse_syslog_timestamp(line)
                if parsed_timestamp is None:
                    continue

                entries.append(LogEntry(
                    log_source=self.source_name,
                    log_timestamp=parsed_timestamp,
                    content=self._strip_syslog_timestamp(line),
                    severity=severity
                ))

            # Set cursor for future incremental collection
            stat = syslog_file.stat()
            self.update_cursor(cursors,
                              byte_offset=stat.st_size,
                              inode=stat.st_ino,
                              last_timestamp=int(time.time()))

            return entries

        except Exception as e:
            raise Exception(f"Failed to collect syslog history: {e}")

    def _parse_syslog_timestamp(self, line: str) -> Optional[int]:
        """Parse syslog timestamp from standard format 'Sep  7 13:14:25' and convert to UTC."""
        import re
        from datetime import datetime, timezone
        try:
            match = re.match(r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})', line.strip())
            if not match:
                return None

            timestamp_str = match.group(1)
            current_year = datetime.now().year
            full_timestamp = f"{current_year} {timestamp_str}"

            dt_local = datetime.strptime(full_timestamp, "%Y %b %d %H:%M:%S")
            dt_local = dt_local.replace(tzinfo=datetime.now().astimezone().tzinfo)
            return int(dt_local.astimezone(timezone.utc).timestamp())
        except Exception as e:
            raise Exception(f"Failed to parse syslog timestamp from '{line[:50]}...': {e}")

    def _strip_syslog_timestamp(self, line: str) -> str:
        """Strip timestamp from syslog line, keeping only message content."""
        import re
        match = re.match(r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(.*)', line.strip())
        if match:
            return match.group(3)
        return line.strip()
