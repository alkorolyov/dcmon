"""
Metric Query Modules

Organized metric querying utilities split by concern:
- latest.py: Latest value queries with aggregation
- timeseries.py: Time-series data retrieval
- rates.py: Rate calculations for counter metrics
- labels.py: Label formatting and GPU mapping
- builder.py: MetricQueryBuilder backwards compatibility wrapper
"""

# Re-export backwards compatibility wrapper
from .builder import MetricQueryBuilder

# Re-export main functions
from .latest import get_latest_metric_value
from .timeseries import get_raw_timeseries, get_timeseries_data
from .rates import calculate_rates_from_raw_data, get_rate_timeseries
from .labels import create_friendly_label, get_all_latest_metrics_for_client

# Re-export sensor constants
from .constants import CPU_SENSORS, VRM_SENSORS

# Convenience functions
from .convenience import get_cpu_temperature, get_vrm_temperature

__all__ = [
    # Backwards compatibility
    'MetricQueryBuilder',

    # Latest value queries
    'get_latest_metric_value',

    # Timeseries queries
    'get_raw_timeseries',
    'get_timeseries_data',

    # Rate calculations
    'calculate_rates_from_raw_data',
    'get_rate_timeseries',

    # Label utilities
    'create_friendly_label',
    'get_all_latest_metrics_for_client',

    # Constants
    'CPU_SENSORS',
    'VRM_SENSORS',

    # Convenience functions
    'get_cpu_temperature',
    'get_vrm_temperature',
]
