"""
Convenience functions for common query patterns.

Provides simple wrappers for frequently used queries
like CPU and VRM temperature readings.
"""

from typing import Optional
from .latest import get_latest_metric_value
from .constants import CPU_SENSORS, VRM_SENSORS


def get_cpu_temperature(client_id: int) -> Optional[float]:
    """Get latest max CPU temperature for client."""
    return get_latest_metric_value(client_id, "ipmi_temp_celsius", CPU_SENSORS, "max")


def get_vrm_temperature(client_id: int) -> Optional[float]:
    """Get latest max VRM temperature for client."""
    return get_latest_metric_value(client_id, "ipmi_temp_celsius", VRM_SENSORS, "max")
