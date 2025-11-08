"""IPMI sensor metrics exporter.

Collects metrics from IPMI sensors including temperature, fan speed, power, and voltage.
Requires ipmitool and appropriate system privileges.
"""

import asyncio
import logging
from typing import List, Optional

from .base import MetricsExporter, MetricPoint


def is_ipmi_available() -> bool:
    """
    Check if IPMI is available (requires root or device access).
    Returns True if IPMI tools and devices are accessible.
    """
    import os
    import subprocess
    from pathlib import Path

    # Check if we have root privileges
    if os.geteuid() != 0:
        # Non-root users might still have access via device permissions
        ipmi_devices = ["/dev/ipmi0", "/dev/ipmi/0", "/dev/ipmidev/0"]
        if not any(Path(dev).exists() for dev in ipmi_devices):
            return False

    # Test if ipmitool command works
    try:
        result = subprocess.run(
            ["ipmitool", "mc", "info"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class IpmiExporter(MetricsExporter):
    """
    IPMI metrics exporter (single-command parser)
    Runs exactly one command: `<ipmi_bin> sensor` and parses the table output.

    Emits per-sensor (labels: sensor):
      - ipmi_temp_celsius{sensor}
      - ipmi_fan_rpm{sensor}
      - ipmi_power_watts{sensor}
      - ipmi_voltage_volts{sensor}
      - ipmi_discrete{sensor}  (for discrete hex/bitfield rows, e.g., ChassisIntr, PROCHOT_CPU)

    Skips 'na' / 'N/A' / non-numeric readings for numeric types.
    """

    def __init__(self, ipmi_bin: str = "ipmitool"):
        self.ipmi_bin = ipmi_bin  # set to "ipmitools" if that's your binary name
        super().__init__("ipmi")

    def is_available(self) -> bool:
        """Check if IPMI is available (device access + privileges)"""
        return is_ipmi_available()

    async def collect(self) -> List[MetricPoint]:
        """Collect IPMI sensor metrics"""
        if not self.available:
            return []
        rows = await self._read_ipmi_sensor_table()
        metrics: List[MetricPoint] = []

        for name, reading, units, status in rows:
            sensor = name.strip()
            units_l = (units or "").strip().lower()
            reading_s = (reading or "").strip().lower()

            # Discrete sensors: value like "0x0" / "0x1" -> emit ipmi_discrete
            if units_l == "discrete":
                val = self._hex_to_int(reading_s)
                if val is not None:
                    metrics.append(MetricPoint("ipmi_discrete", int(val), {"sensor": sensor}))
                continue

            # Convert numeric readings; skip NA
            val = self._to_float(reading_s)
            if val is None:
                continue

            # Normalize units and emit typed metrics
            if units_l in ("degrees c", "celsius", "degc", "c"):
                metrics.append(MetricPoint("ipmi_temp_celsius", int(val), {"sensor": sensor}))
            elif units_l == "rpm":
                metrics.append(MetricPoint("ipmi_fan_rpm", int(val), {"sensor": sensor}))
            elif units_l in ("watts", "w"):
                metrics.append(MetricPoint("ipmi_power_watts", int(val), {"sensor": sensor}))
            elif units_l in ("volts", "v"):
                metrics.append(MetricPoint("ipmi_voltage_volts", float(val), {"sensor": sensor}))
            # (optional) add amps if you want:
            # elif units_l in ("amps", "a"):
            #     metrics.append(MetricPoint("ipmi_current_amps", float(val), {"sensor": sensor}))

        return metrics

    # ----- helpers -----

    async def _read_ipmi_sensor_table(self) -> List[List[str]]:
        """
        Parse the standard table from: `<ipmi_bin> sensor`
        Each data row looks like: NAME | READING | UNITS | STATUS | ...
        Returns rows of [name, reading, units, status]
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self.ipmi_bin, "sensor",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return []

        out, err = await proc.communicate()
        if proc.returncode != 0:
            return []

        rows: List[List[str]] = []
        for ln in out.decode(errors="ignore").splitlines():
            if "|" not in ln:
                continue
            cols = [c.strip() for c in ln.split("|")]
            if len(cols) < 4:
                continue
            name, reading, units, status = cols[0], cols[1], cols[2], cols[3]
            rows.append([name, reading, units, status])
        return rows

    def _to_float(self, s: str) -> Optional[float]:
        if not s or s in ("na", "n/a", "no reading", "disabled"):
            return None
        if s.startswith("0x"):  # discrete hex → not a numeric reading
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _hex_to_int(self, s: str) -> Optional[int]:
        if not s or not s.startswith("0x"):
            return None
        try:
            return int(s, 16)
        except ValueError:
            return None
