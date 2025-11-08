"""
Time-series data retrieval and aggregation.

Handles fetching raw and aggregated time-series data
for metrics visualization and analysis.
"""

import logging
import pandas as pd
from typing import List, Optional, Dict, Union

try:
    from ...models import Client, MetricSeries, MetricPoints
except ImportError:
    from models import Client, MetricSeries, MetricPoints

from .utils import filter_series_by_labels

logger = logging.getLogger("dcmon.server")


def get_raw_timeseries(
    metric_name: Union[str, List[str]],
    start_time: int,
    end_time: int,
    client_ids: Optional[List[int]] = None,
    label_filters: Optional[List[Dict[str, str]]] = None,
    active_only: bool = True
) -> pd.DataFrame:
    """
    Get raw timeseries data without any aggregation.
    Pure data retrieval function.

    Args:
        metric_name: Metric name or list of metric names
        start_time: Start timestamp
        end_time: End timestamp
        client_ids: Optional client ID filter
        label_filters: Optional label filters

    Returns:
        DataFrame with columns: client_id, client_name, timestamp, value, series
    """
    try:
        # Handle both single and multiple metric names
        metric_names = [metric_name] if isinstance(metric_name, str) else metric_name

        # Base series query - select both MetricSeries and Client fields
        base_query = (MetricSeries.select(MetricSeries, Client)
                     .join(Client)
                     .where(MetricSeries.metric_name.in_(metric_names)))

        # Apply client filtering
        if client_ids:
            # Specific clients requested
            base_query = base_query.where(MetricSeries.client.in_(client_ids))
        elif active_only:
            # Default: only active clients (seen in last hour)
            import time
            one_hour_ago = int(time.time()) - 3600
            base_query = base_query.where(
                (Client.last_seen.is_null(False)) &
                (Client.last_seen >= one_hour_ago)
            )

        # Apply label filtering
        filtered_query = filter_series_by_labels(base_query, label_filters)
        series_list = list(filtered_query)

        if not series_list:
            return pd.DataFrame()

        # Get series IDs and client info
        series_ids = [s.id for s in series_list]
        client_info_df = pd.DataFrame([
            {'series': s.id, 'client_id': s.client.id, 'client_name': s.client.hostname}
            for s in series_list
        ])

        # Get metric points (all metrics stored as float in unified table)
        points_query = (MetricPoints.select()
                       .where(
                           (MetricPoints.series.in_(series_ids)) &
                           (MetricPoints.timestamp >= start_time) &
                           (MetricPoints.timestamp <= end_time)
                       )
                       .order_by(MetricPoints.timestamp)
                       .dicts())

        df = pd.DataFrame(list(points_query)) if series_ids else pd.DataFrame()

        if df.empty:
            return pd.DataFrame()

        # Merge with client info using 'series' column
        df = df.merge(client_info_df, on='series', how='left')

        return df

    except Exception as e:
        logger.error(f"Error getting raw timeseries for {metric_names}: {e}")
        return pd.DataFrame()


def get_timeseries_data(
    metric_name: Union[str, List[str]],
    start_time: int,
    end_time: int,
    client_ids: Optional[List[int]] = None,
    label_filters: Optional[List[Dict[str, str]]] = None,
    aggregation: str = "max"
) -> pd.DataFrame:
    """
    Get aggregated timeseries data. Clean wrapper around get_raw_timeseries.
    """
    # Get raw data
    df = get_raw_timeseries(
        metric_name=metric_name,
        start_time=start_time,
        end_time=end_time,
        client_ids=client_ids,
        label_filters=label_filters
    )

    if df.empty or aggregation == "raw":
        return df

    # Simple aggregation mapping
    agg_func = {
        "max": 'max',
        "min": 'min',
        "avg": 'mean',
        "sum": 'sum'
    }.get(aggregation, 'first')

    # Group by client and timestamp, aggregate multiple sensors
    return df.groupby(['client_id', 'client_name', 'timestamp'])['value'].agg(agg_func).reset_index()
