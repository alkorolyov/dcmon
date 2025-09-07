#!/usr/bin/env python3
"""
Centralized Metric Querying Utilities

All metric querying logic consolidated here for AI-friendly code organization.
No logic duplication, clean separation of concerns.
"""

import json
import logging
import pandas as pd
from typing import List, Optional, Dict, Any, Union
from peewee import reduce, Model
import operator

# Support running as script or as package
try:
    from ..models import Client, MetricSeries, MetricPointsInt, MetricPointsFloat
except ImportError:
    from models import Client, MetricSeries, MetricPointsInt, MetricPointsFloat

logger = logging.getLogger("dcmon.server")


class MetricQueryBuilder:
    """Centralized metric querying with label filtering and aggregation."""
    
    @staticmethod
    def filter_series_by_labels(base_query, label_filters: Optional[List[Dict[str, str]]] = None):
        """
        Filter MetricSeries by exact label key-value pairs.
        
        Args:
            base_query: Base MetricSeries query
            label_filters: List of label filters, e.g. [{"sensor": "CPU Temp"}, {"sensor": "VRM Temp"}]
        
        Returns:
            Filtered query
        """
        if not label_filters:
            return base_query
        
        conditions = []
        for label_filter in label_filters:
            for key, value in label_filter.items():
                # Match exact key-value in JSON: {"sensor":"CPU Temp"}
                conditions.append(MetricSeries.labels.contains(f'"{key}":"{value}"'))
        
        if len(conditions) == 1:
            return base_query.where(conditions[0])
        else:
            combined_condition = reduce(operator.or_, conditions)
            return base_query.where(combined_condition)
    
    @staticmethod
    def get_latest_metric_value(client_id: int, metric_name: Union[str, List[str]], 
                               label_filters: Optional[List[Dict[str, str]]] = None,
                               aggregation: Optional[str] = None) -> Optional[float]:
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
            filtered_query = MetricQueryBuilder.filter_series_by_labels(base_query, label_filters)
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
    
    @staticmethod
    def get_timeseries_data(metric_name: str, 
                           start_time: int, end_time: int,
                           client_ids: Optional[List[int]] = None,
                           label_filters: Optional[List[Dict[str, str]]] = None,
                           aggregation: str = "max") -> pd.DataFrame:
        """
        Get timeseries data with label filtering and aggregation.
        
        Args:
            metric_name: Metric name
            start_time: Start timestamp
            end_time: End timestamp  
            client_ids: Optional client ID filter
            label_filters: Optional label filters
            aggregation: Aggregation type (max, min, avg, sum, raw)
        
        Returns:
            DataFrame with columns: client_id, timestamp, value, client_name
        """
        try:
            # Base series query
            base_query = (MetricSeries.select(MetricSeries, Client.hostname)
                         .join(Client)
                         .where(MetricSeries.metric_name == metric_name))
            
            # Filter by clients if specified
            if client_ids:
                base_query = base_query.where(MetricSeries.client.in_(client_ids))
            
            # Apply label filtering
            filtered_query = MetricQueryBuilder.filter_series_by_labels(base_query, label_filters)
            series_list = list(filtered_query)
            
            if not series_list:
                return pd.DataFrame()
            
            # Get series IDs and client info
            series_ids = [s.id for s in series_list]
            client_info_df = pd.DataFrame([
                {'series': s.id, 'client_id': s.client.id, 'client_name': s.client.hostname}
                for s in series_list
            ])
            
            # Get int and float points
            int_query = (MetricPointsInt.select()
                        .where(
                            (MetricPointsInt.series.in_(series_ids)) &
                            (MetricPointsInt.timestamp >= start_time) &
                            (MetricPointsInt.timestamp <= end_time)
                        )
                        .order_by(MetricPointsInt.timestamp)
                        .dicts())
            
            float_query = (MetricPointsFloat.select()
                          .where(
                              (MetricPointsFloat.series.in_(series_ids)) &
                              (MetricPointsFloat.timestamp >= start_time) &
                              (MetricPointsFloat.timestamp <= end_time)
                          )
                          .order_by(MetricPointsFloat.timestamp)
                          .dicts())
            
            int_df = pd.DataFrame(list(int_query)) if series_ids else pd.DataFrame()
            float_df = pd.DataFrame(list(float_query)) if series_ids else pd.DataFrame()
            
            # Combine data
            if not int_df.empty and not float_df.empty:
                df = pd.concat([int_df, float_df], ignore_index=True)
            elif not int_df.empty:
                df = int_df
            elif not float_df.empty:
                df = float_df
            else:
                return pd.DataFrame()
            
            # Merge with client info using 'series' column (matches .dicts() output)
            df = df.merge(client_info_df, on='series', how='left')
            
            # Apply aggregation per client per timestamp
            if aggregation == "max":
                agg_func = 'max'
            elif aggregation == "min":
                agg_func = 'min'
            elif aggregation == "avg":
                agg_func = 'mean'
            elif aggregation == "sum":
                agg_func = 'sum'
            else:  # raw
                agg_func = 'first'
            
            # Group by client and timestamp, aggregate values from multiple sensors
            aggregated_df = df.groupby(['client_id', 'client_name', 'timestamp'])['value'].agg(agg_func).reset_index()
            
            return aggregated_df
            
        except Exception as e:
            logger.error(f"Error getting timeseries for {metric_name}: {e}")
            return pd.DataFrame()


# Convenience functions for common patterns
def get_cpu_temperature(client_id: int) -> Optional[float]:
    """Get latest max CPU temperature for client."""
    cpu_sensors = [{"sensor": "CPU Temp"}, {"sensor": "TEMP_CPU"}]
    return MetricQueryBuilder.get_latest_metric_value(client_id, "ipmi_temp_celsius", cpu_sensors)


def get_vrm_temperature(client_id: int) -> Optional[float]:
    """Get latest max VRM temperature for client."""
    vrm_sensors = [{"sensor": "VRMABCD Temp"}, {"sensor": "VRMEFGH Temp"}, {"sensor": "SOC_VRM Temp"}, {"sensor":"FSC_INDEX1"}]
    return MetricQueryBuilder.get_latest_metric_value(client_id, "ipmi_temp_celsius", vrm_sensors)


def get_cpu_timeseries(start_time: int, end_time: int, client_ids: Optional[List[int]] = None) -> pd.DataFrame:
    """Get CPU temperature timeseries with max aggregation."""
    cpu_sensors = [{"sensor": "CPU Temp"}, {"sensor": "TEMP_CPU"}]
    return MetricQueryBuilder.get_timeseries_data(
        "ipmi_temp_celsius", start_time, end_time, client_ids, cpu_sensors, "max"
    )


def get_vrm_timeseries(start_time: int, end_time: int, client_ids: Optional[List[int]] = None) -> pd.DataFrame:
    """Get VRM temperature timeseries with max aggregation."""
    vrm_sensors = [{"sensor": "VRMABCD Temp"}, {"sensor": "VRMEFGH Temp"}, {"sensor": "SOC_VRM Temp"}, {"sensor":"FSC_INDEX1"}]
    return MetricQueryBuilder.get_timeseries_data(
        "ipmi_temp_celsius", start_time, end_time, client_ids, vrm_sensors, "max"
    )