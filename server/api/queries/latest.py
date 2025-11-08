"""
Latest value queries with aggregation support.

Handles retrieving the most recent metric values with optional
label filtering and aggregation across multiple series.
"""

import logging
from typing import List, Optional, Dict, Union

try:
    from ...models import MetricSeries, MetricPointsInt, MetricPointsFloat
except ImportError:
    from models import MetricSeries, MetricPointsInt, MetricPointsFloat

from .utils import filter_series_by_labels

logger = logging.getLogger("dcmon.server")


def get_latest_metric_value(
    client_id: int,
    metric_name: Union[str, List[str]],
    label_filters: Optional[List[Dict[str, str]]] = None,
    aggregation: Optional[str] = None
) -> Optional[float]:
    """
    Get latest metric value with optional label filtering and aggregation.

    Args:
        client_id: Client ID
        metric_name: Metric name (e.g., "ipmi_temp_celsius") or list of metric names
        label_filters: Label filters, e.g. [{"sensor": "CPU Temp"}]
        aggregation: If None, return latest timestamp value from any series.
                    If specified ("max", "min", "avg", "sum"), aggregate across all matching series at latest timestamp.

    Returns:
        Latest value or None if not found
    """
    try:
        # Handle both single metric name and list of metric names
        metric_names = [metric_name] if isinstance(metric_name, str) else metric_name

        # Base series query for multiple metric names
        base_query = MetricSeries.select().where(
            (MetricSeries.client == client_id) &
            (MetricSeries.metric_name.in_(metric_names))
        )

        # Apply label filtering
        filtered_query = filter_series_by_labels(base_query, label_filters)
        series_list = list(filtered_query)

        if not series_list:
            return None

        series_ids = [s.id for s in series_list]

        if aggregation is None:
            # Original behavior: latest timestamp from any series
            # Try int points first
            latest_point = (MetricPointsInt.select()
                          .where(MetricPointsInt.series.in_(series_ids))
                          .order_by(MetricPointsInt.timestamp.desc())
                          .first())

            if latest_point:
                return float(latest_point.value)

            # Try float points
            latest_point = (MetricPointsFloat.select()
                          .where(MetricPointsFloat.series.in_(series_ids))
                          .order_by(MetricPointsFloat.timestamp.desc())
                          .first())

            if latest_point:
                return float(latest_point.value)

            return None
        else:
            # Aggregation behavior: find latest timestamp, then aggregate across all series at that timestamp
            import time

            # Find the latest timestamp across all series (int and float)
            latest_int_ts = (MetricPointsInt.select(MetricPointsInt.timestamp)
                           .where(MetricPointsInt.series.in_(series_ids))
                           .order_by(MetricPointsInt.timestamp.desc())
                           .scalar())

            latest_float_ts = (MetricPointsFloat.select(MetricPointsFloat.timestamp)
                             .where(MetricPointsFloat.series.in_(series_ids))
                             .order_by(MetricPointsFloat.timestamp.desc())
                             .scalar())

            # Get the most recent timestamp between int and float
            timestamps = [ts for ts in [latest_int_ts, latest_float_ts] if ts is not None]
            if not timestamps:
                return None

            latest_timestamp = max(timestamps)

            # Get all values at the latest timestamp
            values = []

            # Get int values at latest timestamp
            int_points = (MetricPointsInt.select()
                        .where(
                            (MetricPointsInt.series.in_(series_ids)) &
                            (MetricPointsInt.timestamp == latest_timestamp)
                        ))

            for point in int_points:
                values.append(float(point.value))

            # Get float values at latest timestamp
            float_points = (MetricPointsFloat.select()
                          .where(
                              (MetricPointsFloat.series.in_(series_ids)) &
                              (MetricPointsFloat.timestamp == latest_timestamp)
                          ))

            for point in float_points:
                values.append(float(point.value))

            if not values:
                return None

            # Apply aggregation
            if aggregation == "max":
                return max(values)
            elif aggregation == "min":
                return min(values)
            elif aggregation == "avg":
                return sum(values) / len(values)
            elif aggregation == "sum":
                return sum(values)
            else:
                logger.warning(f"Unknown aggregation type: {aggregation}, using max")
                return max(values)

    except Exception as e:
        logger.debug(f"Error getting metric {metric_name} for client {client_id}: {e}")
        return None
