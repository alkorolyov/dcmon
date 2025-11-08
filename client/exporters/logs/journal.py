"""Systemd journal exporter."""

import time
from pathlib import Path
from typing import Dict, List, Optional

from .base import LogEntry, LogExporter


class JournalExporter(LogExporter):
    """Systemd journal exporter."""

    source_name = "journal"

    def is_available(self) -> bool:
        """Check if journalctl is available."""
        import subprocess
        try:
            subprocess.run(['journalctl', '--version'], capture_output=True, timeout=5)
            return True
        except:
            return False

    def collect_incremental(self, cursors: Dict) -> List[LogEntry]:
        """Collect new journal entries using systemd cursor."""
        try:
            import subprocess
            import json

            # Handle missing cursor (first run for this log source)
            if self.source_name not in cursors:
                return self.collect_history(cursors)

            cursor = cursors[self.source_name]
            cmd = ['journalctl', '--output=json', '--no-pager']

            # Use cursor if available
            if cursor.get('cursor'):
                cmd.extend(['--after-cursor', cursor['cursor']])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return []

            entries = []
            last_cursor = cursor.get('cursor', "")

            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue

                try:
                    entry = json.loads(line)
                    message = entry.get('MESSAGE', '')
                    if not message:
                        continue

                    # Extract timestamp
                    timestamp_usec = int(entry.get('__REALTIME_TIMESTAMP', 0))
                    timestamp = timestamp_usec // 1000000  # Convert to seconds

                    # Extract severity
                    priority = entry.get('PRIORITY', '6')  # Default to INFO
                    severity_map = {'0': 'ERROR', '1': 'ERROR', '2': 'ERROR', '3': 'ERROR',
                                   '4': 'WARN', '5': 'INFO', '6': 'INFO', '7': 'DEBUG'}
                    severity = severity_map.get(priority, 'INFO')

                    if not self._should_include_severity(severity):
                        continue

                    # Enhanced content with context
                    content = self._format_journal_content(entry, message)

                    entries.append(LogEntry(
                        log_source=self.source_name,
                        log_timestamp=timestamp,
                        content=content,
                        severity=severity
                    ))

                    # Update cursor
                    last_cursor = entry.get('__CURSOR', last_cursor)

                except (json.JSONDecodeError, ValueError, KeyError):
                    continue

            # Update cursor
            if entries:  # Only update if we got new entries
                self.update_cursor(cursors,
                                  cursor=last_cursor,
                                  last_timestamp=int(time.time()))

            return entries

        except Exception as e:
            raise Exception(f"Failed to collect journal incremental: {e}")

    def collect_history(self, cursors: Dict) -> List[LogEntry]:
        """Collect journal history (first run)."""
        try:
            import subprocess
            import json

            # Get last 1000 entries
            cmd = ['journalctl', '--output=json', '--no-pager', '--lines=1000']

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                raise Exception(f"journalctl command failed: {result.stderr}")

            entries = []
            last_cursor = ""
            entry_count = 0

            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue

                try:
                    entry = json.loads(line)
                    message = entry.get('MESSAGE', '')
                    if not message:
                        continue

                    # Crop to 1000 entries max
                    entry_count += 1
                    if entry_count > 1000:
                        self.logger.info(f"journal history cropped to 1000 entries")
                        break

                    # Extract timestamp
                    timestamp_usec = int(entry.get('__REALTIME_TIMESTAMP', 0))
                    timestamp = timestamp_usec // 1000000

                    # Extract severity
                    priority = entry.get('PRIORITY', '6')
                    severity_map = {'0': 'ERROR', '1': 'ERROR', '2': 'ERROR', '3': 'ERROR',
                                   '4': 'WARN', '5': 'INFO', '6': 'INFO', '7': 'DEBUG'}
                    severity = severity_map.get(priority, 'INFO')

                    if not self._should_include_severity(severity):
                        continue

                    # Enhanced content with context
                    content = self._format_journal_content(entry, message)

                    entries.append(LogEntry(
                        log_source=self.source_name,
                        log_timestamp=timestamp,
                        content=content,
                        severity=severity
                    ))

                    last_cursor = entry.get('__CURSOR', last_cursor)

                except (json.JSONDecodeError, ValueError, KeyError):
                    continue

            # Set cursor for future incremental collection
            if last_cursor:
                self.update_cursor(cursors,
                                  cursor=last_cursor,
                                  last_timestamp=int(time.time()))

            return entries

        except Exception as e:
            raise Exception(f"Failed to collect journal history: {e}")

    def _format_journal_content(self, entry: dict, message: str) -> str:
        """Format journal entry with enhanced context."""
        context_parts = []

        # Add systemd unit if available
        if entry.get('_SYSTEMD_UNIT'):
            context_parts.append(entry['_SYSTEMD_UNIT'])
        elif entry.get('UNIT'):
            context_parts.append(entry['UNIT'])

        # Add service name or identifier
        if entry.get('SYSLOG_IDENTIFIER'):
            identifier = entry['SYSLOG_IDENTIFIER']
            if entry.get('_PID'):
                identifier += f"[{entry['_PID']}]"
            context_parts.append(identifier)

        if context_parts:
            return f"[{'] ['.join(context_parts)}]: {message.strip()}"
        else:
            return message.strip()
