"""
Rate calculation for counter metrics.

Implements Grafana-style rate[5m] calculations for monotonically
increasing counter metrics (network bytes, disk I/O, etc.).
"""

import logging
import pandas as pd
import numpy as np
from typing import List, Optional, Dict, Union

from .timeseries import get_raw_timeseries

logger = logging.getLogger("dcmon.server")


def calculate_rates_from_raw_data(df: pd.DataFrame, rate_window_minutes: int = 5) -> pd.DataFrame:
    """
    Calculate rates from raw timeseries data using efficient pandas operations.

    Args:
        df: Raw timeseries DataFrame with columns: client_id, client_name, timestamp, value
        rate_window_minutes: Rate calculation window in minutes

    Returns:
        DataFrame with columns: client_id, client_name, timestamp, value (rate per second)
    """
    if df.empty:
        return df

    # Do all DataFrame-wide operations first for efficiency
    df = df.copy()
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
    df = df.sort_values(['client_id', 'datetime'])  # Sort once for all groups

    result_groups = []

    # Group by series to calculate rates per metric/device separately
    # This prevents mixing different metrics (e.g., disk_read + disk_write) in same rate calculation
    for (series_id, client_id, client_name), group in df.groupby(['series', 'client_id', 'client_name']):
        if len(group) < 2:
            continue  # Need at least 2 points for rate calculation

        # Group is already sorted, just set index for time-based operations
        group = group.set_index('datetime')

        # Grafana-style rate[Xm] calculation:
        # For each point, look back X minutes and calculate rate from first to last value in that window
        window = f"{rate_window_minutes}min"

        def calculate_window_rate(window_data):
            if len(window_data) < 2:
                return np.nan
            # Rate = (last_value - first_value) / (last_time - first_time)
            first_val = window_data.iloc[0]
            last_val = window_data.iloc[-1]
            time_diff = (window_data.index[-1] - window_data.index[0]).total_seconds()
            if time_diff == 0:
                return np.nan

            # Counter reset detection: if counter decreased, assume reset and return 0
            # Counters should be monotonically increasing
            if last_val < first_val:
                return 0.0

            return (last_val - first_val) / time_diff

        # Apply rolling window rate calculation
        group['rate'] = group['value'].rolling(window).apply(calculate_window_rate, raw=False)

        # Reset index and prepare output
        group = group.reset_index()
        valid = group[group['rate'].notna()].copy()

        if not valid.empty:
            valid['client_id'] = client_id
            valid['client_name'] = client_name
            valid = valid[['timestamp', 'rate', 'client_id', 'client_name']]
            valid = valid.rename(columns={'rate': 'value'})
            result_groups.append(valid)

    return pd.concat(result_groups, ignore_index=True) if result_groups else pd.DataFrame()


def get_rate_timeseries(
    metric_name: Union[str, List[str]],
    start_time: int,
    end_time: int,
    client_ids: Optional[List[int]] = None,
    label_filters: Optional[List[Dict[str, str]]] = None,
    aggregation: str = "sum",
    rate_window_minutes: int = 5,
    active_only: bool = True
) -> pd.DataFrame:
    """
    Calculate rate timeseries using separated functions.

    Args:
        metric_name: Single metric name or list of metric names (for counter metrics)
        start_time: Start timestamp
        end_time: End timestamp
        client_ids: Optional client ID filter
        label_filters: Optional label filters
        aggregation: "sum", "max", "min", "mean", or "raw" (no aggregation)
        rate_window_minutes: Rate calculation window

    Returns:
        DataFrame with columns: client_id, client_name, timestamp, value (rate per second)
    """
    try:
        metric_names = [metric_name] if isinstance(metric_name, str) else metric_name
        # Get raw data using the dedicated raw function
        raw_df = get_raw_timeseries(
            metric_name=metric_names,
            start_time=start_time,
            end_time=end_time,
            client_ids=client_ids,
            label_filters=label_filters,
            active_only=active_only
        )

        if raw_df.empty:
            return raw_df

        # Calculate rates using the dedicated rate calculation function
        rate_df = calculate_rates_from_raw_data(raw_df, rate_window_minutes)

        if rate_df.empty or aggregation == "raw":
            return rate_df

        # Apply aggregation across multiple metrics (e.g., RX + TX)
        agg_func = 'mean' if aggregation == "mean" else aggregation

        final_df = (rate_df.groupby(['client_id', 'client_name', 'timestamp'])['value']
                   .agg(agg_func)
                   .reset_index())

        return final_df

    except Exception as e:
        metric_names = [metric_name] if isinstance(metric_name, str) else metric_name
        logger.error(f"Error calculating rate timeseries for {metric_names}: {e}")
        import traceback
        logger.error(f"Rate calculation traceback:\n{traceback.format_exc()}")
        return pd.DataFrame()
