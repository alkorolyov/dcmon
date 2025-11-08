"""NVMe drive health metrics exporter.

Collects SMART data and health metrics from NVMe drives.
Requires nvme-cli and root privileges.
"""

import asyncio
import json
import logging
from typing import List, Dict, Optional

from .base import MetricsExporter, MetricPoint


def is_nvme_available() -> bool:
    """Check if nvme-cli is available and has device access (requires root for SMART data)"""
    import os
    import subprocess

    # Check if running as root (required for SMART data access)
    if os.geteuid() != 0:
        return False

    # Test if nvme command exists and works
    try:
        result = subprocess.run(
            ["nvme", "list", "-o", "json"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class NvmeExporter(MetricsExporter):
    """
    NVMe metrics exporter (Python-only, replaces nvme.sh)

    Emits per NVMe controller (labels: device, model):
      - nvme_temperature_celsius
      - nvme_available_spare_percent
      - nvme_available_spare_threshold_percent
      - nvme_percentage_used
      - nvme_data_units_read_total
      - nvme_data_units_read_bytes_total
      - nvme_data_units_written_total
      - nvme_data_units_written_bytes_total
      - nvme_power_cycles_total
      - nvme_power_on_hours_total
      - nvme_unsafe_shutdowns_total
      - nvme_media_errors_total
      - nvme_error_log_entries_total
      - nvme_critical_warning
    """

    # NVMe SMART "data units" are 512,000 bytes each (per NVMe spec / nvme-cli)
    DATA_UNIT_BYTES = 512_000

    def __init__(self):
        super().__init__("nvme")

    def is_available(self) -> bool:
        """Check if nvme-cli is available (requires root for SMART data access)"""
        return is_nvme_available()

    async def collect(self) -> List[MetricPoint]:
        if not self.available:
            return []

        devices = await self._list_nvme_devices()
        if not devices:
            return []
        metrics: List[MetricPoint] = []
        for dev_path, model in devices:
            try:
                smart = await self._smart_log(dev_path)
            except Exception:
                continue

            labels = {"device": dev_path, "model": model or "unknown"}

            # Helpers (default to 0 if missing)
            def g(key: str, default=0):
                val = smart.get(key, default)
                try:
                    return int(val)
                except Exception:
                    try:
                        return float(val)
                    except Exception:
                        return default

            # Core SMART values
            temperature_c      = g("temperature")                     # °C
            avail_spare        = g("available_spare")                 # %
            avail_spare_thr    = g("available_spare_threshold")       # %
            percent_used       = g("percentage_used")                 # %
            data_units_read    = g("data_units_read")                 # count
            data_units_written = g("data_units_written")              # count
            power_cycles       = g("power_cycles")
            power_on_hours     = g("power_on_hours")
            unsafe_shutdowns   = g("unsafe_shutdowns")
            media_errors       = g("media_errors")
            error_log_entries  = g("num_err_log_entries")
            critical_warning   = g("critical_warning")

            metrics.extend([
                MetricPoint("nvme_temperature_celsius", int(temperature_c) - 273, labels),
                MetricPoint("nvme_available_spare_percent", int(avail_spare), labels),
                MetricPoint("nvme_available_spare_threshold_percent", int(avail_spare_thr), labels),
                MetricPoint("nvme_percentage_used", int(percent_used), labels),

                MetricPoint("nvme_data_units_read_total", int(data_units_read), labels),
                MetricPoint("nvme_data_units_read_bytes_total", int(data_units_read) * self.DATA_UNIT_BYTES, labels),
                # MetricPoint("nvme_data_units_written_total", float(data_units_written), labels),
                # MetricPoint("nvme_data_units_written_bytes_total", float(data_units_written) * self.DATA_UNIT_BYTES, labels),

                # MetricPoint("nvme_power_cycles_total", int(power_cycles), labels),
                MetricPoint("nvme_power_on_hours_total", int(power_on_hours), labels),
                MetricPoint("nvme_unsafe_shutdowns_total", int(unsafe_shutdowns), labels),
                MetricPoint("nvme_media_errors_total", int(media_errors), labels),
                MetricPoint("nvme_error_log_entries_total", int(error_log_entries), labels),
                MetricPoint("nvme_critical_warning", int(critical_warning), labels),
            ])

        return metrics

    # ---------- helpers ----------

    async def _list_nvme_devices(self) -> List[tuple]:
        """
        Returns a list of (device_path, model) for NVMe controllers,
        e.g. [('/dev/nvme0', 'SAMSUNG MZVL...'), ('/dev/nvme1', '...')]
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvme", "list", "-o", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
            if proc.returncode != 0:
                return []

            data = json.loads(out.decode() or "{}")
            devs = []
            # nvme-cli json usually has "Devices": [{ "DevicePath": "/dev/nvme0", "ModelNumber": "...", ...}, ...]
            for d in data.get("Devices", []):
                path = d.get("DevicePath")
                model = d.get("ModelNumber") or d.get("Model") or d.get("ModelNumber ")  # be tolerant
                if path and path.startswith("/dev/nvme"):
                    devs.append((path, model))
            return devs
        except Exception:
            return []

    async def _smart_log(self, device_path: str) -> Dict:
        """
        Fetch SMART log as a dict for the given NVMe device (controller).
        """
        proc = await asyncio.create_subprocess_exec(
            "nvme", "smart-log", device_path, "-o", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"nvme smart-log failed for {device_path}: {err.decode().strip()}")
        try:
            return json.loads(out.decode() or "{}")
        except Exception as e:
            raise RuntimeError(f"bad JSON from nvme smart-log {device_path}: {e}")
