"""
Latest value queries with aggregation support.

Handles retrieving the most recent metric values with optional
label filtering and aggregation across multiple series.
"""

import logging
from typing import List, Optional, Dict, Union

try:
    from ...models import MetricSeries, MetricPoints
except ImportError:
    from models import MetricSeries, MetricPoints

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
            latest_point = (MetricPoints.select()
                          .where(MetricPoints.series.in_(series_ids))
                          .order_by(MetricPoints.timestamp.desc())
                          .first())

            if latest_point:
                return float(latest_point.value)

            return None
        else:
            # Aggregation behavior: find latest timestamp, then aggregate across all series at that timestamp
            # Find the latest timestamp across all series
            latest_timestamp = (MetricPoints.select(MetricPoints.timestamp)
                              .where(MetricPoints.series.in_(series_ids))
                              .order_by(MetricPoints.timestamp.desc())
                              .scalar())

            if latest_timestamp is None:
                return None

            # Get all values at the latest timestamp
            points = (MetricPoints.select()
                    .where(
                        (MetricPoints.series.in_(series_ids)) &
                        (MetricPoints.timestamp == latest_timestamp)
                    ))

            values = [float(point.value) for point in points]

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
