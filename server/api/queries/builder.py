"""
MetricQueryBuilder backwards compatibility wrapper.

Provides the original MetricQueryBuilder class interface
while delegating to the new modular query functions.
"""

from .latest import get_latest_metric_value
from .timeseries import get_raw_timeseries, get_timeseries_data
from .rates import calculate_rates_from_raw_data, get_rate_timeseries
from .labels import create_friendly_label, get_all_latest_metrics_for_client, _gpu_mapping
from .utils import filter_series_by_labels


class MetricQueryBuilder:
    """
    Centralized metric querying with label filtering and aggregation.

    This class maintains the original API while delegating to modular functions.
    """

    # Class variable for GPU mapping (backwards compatibility)
    _gpu_mapping = _gpu_mapping

    @staticmethod
    def filter_series_by_labels(base_query, label_filters=None):
        """Filter MetricSeries by exact label key-value pairs."""
        return filter_series_by_labels(base_query, label_filters)

    @staticmethod
    def get_latest_metric_value(client_id, metric_name, label_filters=None, aggregation=None):
        """Get latest metric value with optional label filtering and aggregation."""
        return get_latest_metric_value(client_id, metric_name, label_filters, aggregation)

    @staticmethod
    def get_raw_timeseries(metric_name, start_time, end_time, client_ids=None, label_filters=None, active_only=True):
        """Get raw timeseries data without any aggregation."""
        return get_raw_timeseries(metric_name, start_time, end_time, client_ids, label_filters, active_only)

    @staticmethod
    def get_timeseries_data(metric_name, start_time, end_time, client_ids=None, label_filters=None, aggregation="max"):
        """Get aggregated timeseries data."""
        return get_timeseries_data(metric_name, start_time, end_time, client_ids, label_filters, aggregation)

    @staticmethod
    def calculate_rates_from_raw_data(df, rate_window_minutes=5):
        """Calculate rates from raw timeseries data."""
        return calculate_rates_from_raw_data(df, rate_window_minutes)

    @staticmethod
    def get_rate_timeseries(metric_name, start_time, end_time, client_ids=None, label_filters=None, aggregation="sum", rate_window_minutes=5, active_only=True):
        """Calculate rate timeseries."""
        return get_rate_timeseries(metric_name, start_time, end_time, client_ids, label_filters, aggregation, rate_window_minutes, active_only)

    @staticmethod
    def get_all_latest_metrics_for_client(client_id):
        """Get ALL latest metrics for a client."""
        return get_all_latest_metrics_for_client(client_id)

    @staticmethod
    def _create_friendly_label(labels_dict, metric_name):
        """Create user-friendly labels for metrics."""
        return create_friendly_label(labels_dict, metric_name)
