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
from peewee import reduce, Model, fn, Case
import operator

# Support running as script or as package
try:
    from ..models import Client, MetricSeries, MetricPointsInt, MetricPointsFloat
except ImportError:
    from models import Client, MetricSeries, MetricPointsInt, MetricPointsFloat

logger = logging.getLogger("dcmon.server")

# Centralized sensor mappings for different motherboard types
CPU_SENSORS = [{"sensor": "CPU Temp"}, {"sensor": "TEMP_CPU"}]
VRM_SENSORS = [{"sensor": "CPU_VRM Temp"}, {"sensor": "SOC_VRM Temp"}, {"sensor": "VRMABCD Temp"}, {"sensor": "VRMEFGH Temp"}, {"sensor": "FSC_INDEX1"}]


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
    def get_raw_timeseries(metric_name: Union[str, List[str]], 
                          start_time: int, end_time: int,
                          client_ids: Optional[List[int]] = None,
                          label_filters: Optional[List[Dict[str, str]]] = None,
                          active_only: bool = True) -> pd.DataFrame:
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
            
            # Merge with client info using 'series' column
            df = df.merge(client_info_df, on='series', how='left')
            
            return df
            
        except Exception as e:
            logger.error(f"Error getting raw timeseries for {metric_names}: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_timeseries_data(metric_name: Union[str, List[str]], 
                           start_time: int, end_time: int,
                           client_ids: Optional[List[int]] = None,
                           label_filters: Optional[List[Dict[str, str]]] = None,
                           aggregation: str = "max") -> pd.DataFrame:
        """
        Get aggregated timeseries data. Clean wrapper around get_raw_timeseries.
        """
        # Get raw data
        df = MetricQueryBuilder.get_raw_timeseries(
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
    
    @staticmethod
    def get_all_latest_metrics_for_client(client_id: int) -> Dict[str, Dict[str, float]]:
        """
        Single optimized query to get ALL latest metrics for a client.
        
        Returns structured dict:
        {
            "ipmi_temp_celsius": {"CPU Temp": 45.0, "VRM Temp": 38.0, ...},
            "gpu_temperature": {"GPU0": 67.0, "GPU1": 72.0, ...}, 
            "fs_used_bytes": {"/": 50000000.0, "/docker": 25000000.0, ...},
            "psu_input_power_watts": {"PSU1": 450.0, "PSU2": 380.0, ...},
            # ... all metrics grouped by name with labels as identifier
        }
        """
        try:
            import json
            
            # Get all series for this client with latest points
            # We need to join series with their latest metric points
            all_metrics = {}
            
            # Get all series for this client
            series_query = (MetricSeries.select()
                          .where(MetricSeries.client == client_id))
            
            for series in series_query:
                metric_name = series.metric_name
                
                # Parse labels to create identifier
                try:
                    labels_dict = json.loads(series.labels) if series.labels else {}
                except json.JSONDecodeError:
                    labels_dict = {}
                
                # Create friendly label identifier
                label_id = MetricQueryBuilder._create_friendly_label(labels_dict, metric_name)
                
                # Get latest value for this series
                latest_value = None
                
                # Try integer points first
                if series.value_type == "int":
                    latest_point = (MetricPointsInt.select()
                                  .where(MetricPointsInt.series == series.id)
                                  .order_by(MetricPointsInt.timestamp.desc())
                                  .first())
                    if latest_point:
                        latest_value = float(latest_point.value)
                else:
                    # Try float points
                    latest_point = (MetricPointsFloat.select()
                                  .where(MetricPointsFloat.series == series.id) 
                                  .order_by(MetricPointsFloat.timestamp.desc())
                                  .first())
                    if latest_point:
                        latest_value = float(latest_point.value)
                
                # Store in structured dict
                if latest_value is not None:
                    if metric_name not in all_metrics:
                        all_metrics[metric_name] = {}
                    all_metrics[metric_name][label_id] = latest_value
            
            return all_metrics
            
        except Exception as e:
            logger.error(f"Error getting all latest metrics for client {client_id}: {e}")
            return {}
    
    # Class variable to maintain consistent GPU numbering across all metrics
    _gpu_mapping = {}
    
    @staticmethod
    def _create_friendly_label(labels_dict: dict, metric_name: str) -> str:
        """Create user-friendly labels for metrics."""
        import re
        
        # Handle GPU labels - map PCI addresses and indices to sequential GPU1, GPU2, etc
        if 'bus_id' in labels_dict:
            # Handle PCI addresses like "01:00.0", "C1:00.0" -> GPU1, GPU2, etc
            bus_id = labels_dict['bus_id']
            
            # Check if we already have this bus_id mapped
            if bus_id not in MetricQueryBuilder._gpu_mapping:
                # Assign the next available GPU number
                gpu_count = len(MetricQueryBuilder._gpu_mapping) + 1
                MetricQueryBuilder._gpu_mapping[bus_id] = gpu_count
            
            return f"GPU{MetricQueryBuilder._gpu_mapping[bus_id]}"
            
        elif 'gpu_index' in labels_dict:
            gpu_index = labels_dict['gpu_index']
            if gpu_index not in MetricQueryBuilder._gpu_mapping:
                gpu_count = len(MetricQueryBuilder._gpu_mapping) + 1
                MetricQueryBuilder._gpu_mapping[gpu_index] = gpu_count
            return f"GPU{MetricQueryBuilder._gpu_mapping[gpu_index]}"
            
        elif 'device' in labels_dict and ('gpu' in metric_name or 'utilization' in metric_name):
            # Handle device names like "card0" -> GPU1
            device = labels_dict['device']
            card_match = re.search(r'card(\d+)', device)
            if card_match:
                card_num = card_match.group(1)
                if card_num not in MetricQueryBuilder._gpu_mapping:
                    gpu_count = len(MetricQueryBuilder._gpu_mapping) + 1
                    MetricQueryBuilder._gpu_mapping[card_num] = gpu_count
                return f"GPU{MetricQueryBuilder._gpu_mapping[card_num]}"
                
            # Remove /dev/ prefix if present
            if device.startswith('/dev/'):
                device = device[5:]
                
            # Map other device names consistently
            if device not in MetricQueryBuilder._gpu_mapping:
                gpu_count = len(MetricQueryBuilder._gpu_mapping) + 1
                MetricQueryBuilder._gpu_mapping[device] = gpu_count
            return f"GPU{MetricQueryBuilder._gpu_mapping[device]}"
            
        # Handle NVMe labels - just strip /dev/ prefix, keep original name
        elif 'device' in labels_dict and 'nvme' in labels_dict['device'].lower():
            device = labels_dict['device']
            if device.startswith('/dev/'):
                return device[5:]  # /dev/nvme0n1 -> nvme0n1
            return device
            
        # Handle mountpoint labels - map to friendly names  
        elif 'mountpoint' in labels_dict:
            mountpoint = labels_dict['mountpoint']
            if mountpoint == '/':
                return 'root'
            elif mountpoint == '/var/lib/docker' or 'docker' in mountpoint:
                return 'docker'
            elif mountpoint.startswith('/'):
                return mountpoint[1:] or 'root'  # Remove leading slash
            return mountpoint
            
        # Handle PSU labels
        elif 'psu_id' in labels_dict:
            return f"PSU{labels_dict['psu_id']}"
            
        # Handle IPMI sensor labels - keep as is
        elif 'sensor' in labels_dict:
            return labels_dict['sensor']
            
        # Handle regular device labels - strip /dev/ prefix
        elif 'device' in labels_dict:
            device = labels_dict['device']
            if device.startswith('/dev/'):
                return device[5:]  # Remove /dev/ prefix
            return device
            
        # Default fallback - use meaningful names instead of "default"
        else:
            if labels_dict:
                # Use first available label value
                return next(iter(labels_dict.values()))
            else:
                # Create meaningful name from metric name
                if "fs_" in metric_name:
                    if "bytes" in metric_name:
                        return metric_name.replace('fs_', '').replace('_bytes', '').replace('_', ' ').title()
                    return "filesystem"
                elif "cpu_" in metric_name:
                    return "CPU"
                elif "memory_" in metric_name:
                    return "Memory" 
                elif "network_" in metric_name:
                    return "Network"
                elif "node_" in metric_name:
                    return metric_name.replace('node_', '').replace('_', ' ').title()
                else:
                    # Use cleaned metric name as fallback
                    return metric_name.replace('_', ' ').title()

    @staticmethod
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
        
        for (client_id, client_name), group in df.groupby(['client_id', 'client_name']):
            if len(group) < 2:
                continue  # Need at least 2 points for rate calculation
                
            # Group is already sorted, just set index for time-based operations
            group = group.set_index('datetime')
            
            # Calculate rate using pandas diff operations
            group['rate'] = group['value'].diff() / group.index.to_series().diff().dt.total_seconds()
            
            # Apply rolling window for smoothing (Grafana-style windowed rates)
            group['rate_windowed'] = group['rate'].rolling(f"{rate_window_minutes}min").mean()
            
            # Reset index and prepare output
            group = group.reset_index()
            valid = group[group['rate_windowed'].notna()].copy()
            
            if not valid.empty:
                valid['client_id'] = client_id
                valid['client_name'] = client_name
                valid = valid[['timestamp', 'rate_windowed', 'client_id', 'client_name']]
                valid = valid.rename(columns={'rate_windowed': 'value'})
                result_groups.append(valid)
        
        return pd.concat(result_groups, ignore_index=True) if result_groups else pd.DataFrame()

    @staticmethod
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
            raw_df = MetricQueryBuilder.get_raw_timeseries(
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
            rate_df = MetricQueryBuilder.calculate_rates_from_raw_data(raw_df, rate_window_minutes)
            
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


# Convenience functions for common patterns  
def get_cpu_temperature(client_id: int) -> Optional[float]:
    """Get latest max CPU temperature for client."""
    return MetricQueryBuilder.get_latest_metric_value(client_id, "ipmi_temp_celsius", CPU_SENSORS, "max")


def get_vrm_temperature(client_id: int) -> Optional[float]:
    """Get latest max VRM temperature for client."""
    return MetricQueryBuilder.get_latest_metric_value(client_id, "ipmi_temp_celsius", VRM_SENSORS, "max")