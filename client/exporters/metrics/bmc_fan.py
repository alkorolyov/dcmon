"""BMC fan control metrics exporter.

Collects BMC fan mode and zone speed metrics for Supermicro motherboards.
Requires IPMI access and compatible hardware.
"""

import logging
from typing import List, Dict

from .base import MetricsExporter, MetricPoint


def is_supermicro_compatible(mdb_name: str) -> bool:
    """Check if motherboard supports BMC fan control based on hardware detection"""
    if not mdb_name:
        return False

    mdb_upper = mdb_name.upper()
    if "SUPERMICRO" not in mdb_upper:
        return False

    # Check for supported series (X9, X10, X11, X12, H11, H12)
    supported_series = ['X9', 'X10', 'X11', 'X12', 'H11', 'H12']
    return any(series in mdb_upper for series in supported_series)


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


class BMCFanExporter(MetricsExporter):
    """Exports BMC fan control metrics via IPMI"""

    def __init__(self, hw_info: Dict = None):
        self.hw_info = hw_info or {}
        # Import FanController here to avoid circular dependency
        try:
            from exporters.fans import FanController
        except ImportError:
            from fans import FanController
        self.fan_ctrl = FanController()  # Create once and reuse
        super().__init__("bmc_fan")

    def is_available(self) -> bool:
        """Check if BMC fan control is available (Supermicro hardware + IPMI access)"""
        mdb_name = self.hw_info.get("mdb_name", "")
        return is_supermicro_compatible(mdb_name) and is_ipmi_available()

    async def collect(self) -> List[MetricPoint]:
        """Collect BMC fan metrics"""
        if not self.available:
            return []

        metrics = []

        try:
            # Use cached fan controller instance
            status = await self.fan_ctrl.get_fan_status()

            # BMC Fan Mode metric
            if status.get('bmc_mode_value') is not None:
                metrics.append(MetricPoint(
                    "bmc_fan_mode",
                    status['bmc_mode_value']
                ))

            # Fan zone speed metrics
            zone_0_speed = status.get('zone_0_speed')
            if zone_0_speed is not None:
                metrics.append(MetricPoint(
                    "bmc_fan_zone_speed",
                    zone_0_speed,
                    {"zone": "0"}
                ))

            zone_1_speed = status.get('zone_1_speed')
            if zone_1_speed is not None:
                metrics.append(MetricPoint(
                    "bmc_fan_zone_speed",
                    zone_1_speed,
                    {"zone": "1"}
                ))

        except Exception as e:
            # Don't break metrics collection if IPMI fails
            self.logger.debug(f"BMC fan metrics unavailable: {e}")

        return metrics
