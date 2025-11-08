"""Script Exporter - Base class for script-based exporters"""
import asyncio
import logging
from pathlib import Path
from typing import List

from .base import MetricsExporter, MetricPoint


class ScriptExporter(MetricsExporter):
    """Base class for script-based exporters"""

    def __init__(self, name: str, script_path: str, logger: logging.Logger):
        super().__init__(name, logger)
        self.script_path = Path(script_path)

    async def collect(self) -> List[MetricPoint]:
        """Run script and parse Prometheus format output"""
        if not self.script_path.exists():
            self.logger.warning(f"Script not found: {self.script_path}")
            return []

        try:
            # Run script with timeout
            process = await asyncio.create_subprocess_exec(
                str(self.script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)

            if process.returncode != 0:
                self.logger.error(f"{self.name} script failed: {stderr.decode()}")
                return []

            # Parse Prometheus format output
            return self._parse_prometheus_output(stdout.decode())

        except asyncio.TimeoutError:
            self.logger.error(f"{self.name} script timeout")
            return []
        except Exception as e:
            self.logger.error(f"{self.name} script error: {e}")
            return []

    def _parse_prometheus_output(self, output: str) -> List[MetricPoint]:
        """Parse Prometheus format metrics"""
        metrics = []

        for line in output.strip().split('\n'):
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue

            try:
                # Parse metric line: metric_name{labels} value
                if '{' in line:
                    # Metric with labels
                    metric_part, value_str = line.rsplit(' ', 1)
                    metric_name, labels_str = metric_part.split('{', 1)
                    labels_str = labels_str.rstrip('}')

                    # Parse labels
                    labels = {}
                    if labels_str:
                        for label_pair in labels_str.split(','):
                            if '=' in label_pair:
                                key, val = label_pair.split('=', 1)
                                labels[key.strip()] = val.strip().strip('"')
                else:
                    # Metric without labels
                    parts = line.split()
                    if len(parts) >= 2:
                        metric_name = parts[0]
                        value_str = parts[1]
                        labels = {}

                value = float(value_str)
                metrics.append(MetricPoint(metric_name, value, labels))

            except (ValueError, IndexError) as e:
                self.logger.debug(f"Failed to parse metric line: {line} - {e}")
                continue

        return metrics
