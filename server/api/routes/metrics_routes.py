#!/usr/bin/env python3
"""
Metrics Routes - Metric Submission, Queries, and Time Series
"""

import json
import logging
import time
from typing import List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

# Support running as script or as package
try:
    from ...models import Client, MetricSeries, MetricPointsInt, MetricPointsFloat, LogEntry
    from ..schemas import MetricsBatchRequest
    from ..dependencies import AuthDependencies
    from ..metric_queries import MetricQueryBuilder, get_cpu_timeseries, get_vrm_timeseries
except ImportError:
    from models import Client, MetricSeries, MetricPointsInt, MetricPointsFloat, LogEntry
    from api.schemas import MetricsBatchRequest
    from api.dependencies import AuthDependencies
    from api.metric_queries import MetricQueryBuilder, get_cpu_timeseries, get_vrm_timeseries

logger = logging.getLogger("dcmon.server")


def create_metrics_routes(auth_deps: AuthDependencies) -> APIRouter:
    """Create metrics-related routes."""
    router = APIRouter()

    @router.post("/api/metrics")
    def submit_metrics(body: MetricsBatchRequest, client: Client = Depends(auth_deps.require_client_auth)):
        """Submit metrics batch from client."""
        now = int(time.time())
        int_points = []
        float_points = []
        
        for m in body.metrics:
            if m.timestamp > now + 300:
                raise HTTPException(status_code=422, detail=f"metric timestamp too far in future: {m.timestamp}")
            
            # Get or create metric series
            labels_json = json.dumps(m.labels) if m.labels else None
            series = MetricSeries.get_or_create_series(
                client_id=client.id,
                metric_name=m.metric_name, 
                labels=labels_json,
                value_type=m.value_type
            )
            
            # Prepare data for appropriate points table
            if m.value_type == "int":
                int_points.append({
                    "series": series.id,
                    "timestamp": m.timestamp,
                    "value": int(m.value)
                })
            else:  # float
                float_points.append({
                    "series": series.id,
                    "timestamp": m.timestamp,
                    "value": m.value
                })
        
        # Bulk insert points
        inserted_total = 0
        if int_points:
            inserted_int = MetricPointsInt.insert_many(int_points).on_conflict_ignore().execute()
            inserted_total += int(inserted_int or 0)
            
        if float_points:
            inserted_float = MetricPointsFloat.insert_many(float_points).on_conflict_ignore().execute()
            inserted_total += int(inserted_float or 0)

        # Process log entries
        inserted_logs = 0
        if body.logs:
            log_entries = []
            current_time = int(time.time())
            
            for log_data in body.logs:
                log_entries.append({
                    "client": client.id,
                    "log_source": log_data.log_source,
                    "log_timestamp": log_data.log_timestamp,
                    "received_timestamp": current_time,
                    "content": log_data.content,
                    "severity": log_data.severity
                })
            
            if log_entries:
                inserted_logs = LogEntry.insert_many(log_entries).execute()
                logger.debug(f"Log entries from client {client.id} ({client.hostname}): received {len(body.logs)}, inserted {inserted_logs}")

        # Hardware change detection
        if body.hw_hash and body.hw_hash != client.hw_hash:
            logger.warning(f"Hardware changed on client {client.id} ({client.hostname})")
            client.hw_hash = body.hw_hash
            client.save()
        
        client.update_last_seen()
        logger.debug(f"Metrics from client {client.id} ({client.hostname}): received {len(body.metrics)}, inserted {inserted_total}")
        
        response = {"received": len(body.metrics), "inserted": inserted_total}
        if body.logs:
            response.update({"logs_received": len(body.logs), "logs_inserted": inserted_logs})
        return response

    @router.get("/api/metrics", dependencies=[Depends(auth_deps.require_admin_auth)])
    def query_metrics(
        client_id: Optional[int] = Query(None, ge=1),
        metric_name: Optional[List[str]] = Query(None),
        start: Optional[int] = Query(None),
        end: Optional[int] = Query(None),
        limit: int = Query(1000, ge=1, le=10000),
    ):
        """Query metrics with filtering (admin only)."""
        # Build query for metric series
        series_query = MetricSeries.select()
        if client_id:
            series_query = series_query.where(MetricSeries.client == client_id)
        if metric_name:
            series_query = series_query.where(MetricSeries.metric_name.in_(metric_name))
        
        series_list = list(series_query)
        if not series_list:
            return {"metrics": []}
        
        series_ids = [s.id for s in series_list]
        out = []
        
        # Query float points
        float_query = MetricPointsFloat.select().where(MetricPointsFloat.series.in_(series_ids))
        if start:
            float_query = float_query.where(MetricPointsFloat.timestamp >= start)
        if end:
            float_query = float_query.where(MetricPointsFloat.timestamp <= end)
        float_query = float_query.order_by(MetricPointsFloat.timestamp.desc()).limit(limit // 2)
        
        for point in float_query:
            series = next(s for s in series_list if s.id == point.series.id)
            out.append({
                "client_id": series.client.id,
                "timestamp": point.timestamp,
                "metric_name": series.metric_name,
                "value_float": point.value,
                "value_int": None,
                "labels": json.loads(series.labels) if series.labels else None,
            })
        
        # Query int points
        int_query = MetricPointsInt.select().where(MetricPointsInt.series.in_(series_ids))
        if start:
            int_query = int_query.where(MetricPointsInt.timestamp >= start)
        if end:
            int_query = int_query.where(MetricPointsInt.timestamp <= end)
        int_query = int_query.order_by(MetricPointsInt.timestamp.desc()).limit(limit // 2)
        
        for point in int_query:
            series = next(s for s in series_list if s.id == point.series.id)
            out.append({
                "client_id": series.client.id,
                "timestamp": point.timestamp,
                "metric_name": series.metric_name,
                "value_float": None,
                "value_int": point.value,
                "labels": json.loads(series.labels) if series.labels else None,
            })
        
        # Sort by timestamp descending
        out.sort(key=lambda x: x["timestamp"], reverse=True)
        return {"metrics": out[:limit]}

    @router.get("/api/timeseries/{metric_name}")
    def get_timeseries(
        metric_name: str,
        seconds: int = Query(86400),  # Default 24 hours = 86400 seconds
        client_ids: Optional[List[int]] = Query(None),
        active_only: bool = Query(True),  # Default to active clients only
        since_timestamp: Optional[int] = Query(None),  # For incremental queries
        until_timestamp: Optional[int] = Query(None),  # For gap-filling queries
        aggregation: str = Query("max", pattern="^(max|min|avg|sum|raw)$"),
        sensor: Optional[str] = Query(None),  # Simple sensor filtering (e.g., "CPU")
        admin_auth: bool = Depends(auth_deps.require_admin_auth)
    ):
        """
        General-purpose timeseries endpoint for dashboard charts.
        Uses Basic Auth authentication compatible with dashboard.
        """
        try:
            import time as time_module
            query_start = time_module.time()
            
            # Calculate time range
            end_time = int(time.time())
            
            # Use incremental timestamps if provided, otherwise use seconds range
            if since_timestamp is not None:
                start_time = since_timestamp
                if until_timestamp is not None:
                    end_time = until_timestamp
            else:
                start_time = end_time - seconds
            
            # Get series for the requested metric(s) with smart client filtering
            series_start = time_module.time()
            
            # Handle comma-separated metric names (e.g., "psu_temp1_celsius,psu_temp2_celsius")
            metric_names = [name.strip() for name in metric_name.split(',')]
            if len(metric_names) == 1:
                # Single metric - use exact match
                series_query = (MetricSeries.select()
                              .join(Client)
                              .where(MetricSeries.metric_name == metric_names[0]))
            else:
                # Multiple metrics - use IN clause
                series_query = (MetricSeries.select()
                              .join(Client)
                              .where(MetricSeries.metric_name.in_(metric_names)))
            
            # Apply client filtering
            if client_ids:
                # Specific clients requested
                series_query = series_query.where(MetricSeries.client.in_(client_ids))
            elif active_only:
                # Default: only active clients (seen in last hour)
                one_hour_ago = int(time.time()) - 3600
                series_query = series_query.where(
                    (Client.last_seen.is_null(False)) &
                    (Client.last_seen >= one_hour_ago)
                )
                
            series_list = list(series_query)
            series_time = time_module.time() - series_start
            
            if not series_list:
                return {"data": [[]], "series": [{}], "clients": {}, "metric": metric_name}
            
            # Use pandas for efficient time series processing
            series_ids = [s.id for s in series_list]
            
            # Create client info DataFrame for vectorized merge (use 'series' to match .dicts() output)
            client_info_df = pd.DataFrame([
                {'series': s.id, 'client_id': s.client.id, 'client_name': s.client.hostname}
                for s in series_list
            ])
            
            # Vectorized data collection using pandas
            vectorized_start = time_module.time()
            
            # Get int points using vectorized .dicts() approach
            int_query = (MetricPointsInt.select()
                        .where(
                            (MetricPointsInt.series.in_(series_ids)) &
                            (MetricPointsInt.timestamp >= start_time) &
                            (MetricPointsInt.timestamp <= end_time)
                        )
                        .order_by(MetricPointsInt.timestamp)
                        .dicts())
            
            int_df = pd.DataFrame(list(int_query)) if series_ids else pd.DataFrame()
            
            # Get float points using vectorized .dicts() approach
            float_query = (MetricPointsFloat.select()
                          .where(
                              (MetricPointsFloat.series.in_(series_ids)) &
                              (MetricPointsFloat.timestamp >= start_time) &
                              (MetricPointsFloat.timestamp <= end_time)
                          )
                          .order_by(MetricPointsFloat.timestamp)
                          .dicts())
            
            float_df = pd.DataFrame(list(float_query)) if series_ids else pd.DataFrame()
            
            # Combine int and float data vectorized
            if not int_df.empty and not float_df.empty:
                df = pd.concat([int_df, float_df], ignore_index=True)
            elif not int_df.empty:
                df = int_df
            elif not float_df.empty:
                df = float_df
            else:
                return {"data": {}, "clients": {}, "metric": metric_name, "time_range": {"start": start_time, "end": end_time}}
            
            # Vectorized client info merge - use 'series' field from .dicts() output
            df = df.merge(client_info_df, on='series', how='left')
            df['value'] = df['value'].astype(float)
            
            vectorized_time = time_module.time() - vectorized_start
            
            # Vectorized aggregation
            if aggregation == "max":
                agg_func = 'max'
            elif aggregation == "min":
                agg_func = 'min'
            elif aggregation == "avg":
                agg_func = 'mean'
            elif aggregation == "sum":
                agg_func = 'sum'
            else:  # raw - take first value
                agg_func = 'first'
            
            # Vectorized groupby aggregation
            aggregated_df = df.groupby(['client_id', 'client_name', 'timestamp'])['value'].agg(agg_func).reset_index()
            
            # Create client names mapping
            client_names = aggregated_df.groupby('client_id')['client_name'].first().to_dict()
            
            # Ultra-fast vectorized data structure creation
            client_data = {}
            for client_id in client_names.keys():
                client_df = aggregated_df[aggregated_df['client_id'] == client_id]
                if not client_df.empty:
                    # Vectorized conversion - much faster than iterrows()
                    client_data[client_id] = [
                        {"timestamp": int(ts), "value": float(val)} 
                        for ts, val in zip(client_df['timestamp'].values, client_df['value'].values)
                    ]
                else:
                    client_data[client_id] = []
            
            # Determine unit based on metric name
            unit_map = {
                "gpu_temperature": "°C",
                "cpu_temp_celsius": "°C", 
                "cpu_usage_percent": "%",
                "memory_usage_percent": "%",
                "disk_usage_percent": "%",
                "gpu_power_draw": "W",
                "gpu_fan_speed": "%",
                "ipmi_fan_rpm": " RPM"
            }
            unit = unit_map.get(metric_name, "")
            
            # Log timing information for performance monitoring
            total_time = time_module.time() - query_start
            
            # Import format_elapsed_time for better console output
            try:
                from ...web.template_helpers import format_elapsed_time
            except ImportError:
                from web.template_helpers import format_elapsed_time
            
            logger.debug(f"Timeseries {metric_name}: {format_elapsed_time(total_time)}, {len(aggregated_df)} records (CLEANED)")
            
            # Use specific helper functions for optimal sensor filtering
            if metric_name == "ipmi_temp_celsius" and sensor:
                if sensor.upper() == "CPU":
                    # Use dedicated CPU helper with exact sensor names
                    clean_df = get_cpu_timeseries(start_time, end_time, client_ids)
                    if not clean_df.empty:
                        client_data = {}
                        client_names = {row['client_id']: row['client_name'] for _, row in clean_df[['client_id', 'client_name']].drop_duplicates().iterrows()}
                        for client_id, group in clean_df.groupby('client_id'):
                            client_data[client_id] = list(zip(group['timestamp'].tolist(), group['value'].tolist()))
                        logger.debug(f"Timeseries {metric_name}: CPU HELPER used, {len(clean_df)} records")
                        
                elif sensor.upper() == "VRM":
                    # Use dedicated VRM helper with exact sensor names  
                    clean_df = get_vrm_timeseries(start_time, end_time, client_ids)
                    if not clean_df.empty:
                        client_data = {}
                        client_names = {row['client_id']: row['client_name'] for _, row in clean_df[['client_id', 'client_name']].drop_duplicates().iterrows()}
                        for client_id, group in clean_df.groupby('client_id'):
                            client_data[client_id] = list(zip(group['timestamp'].tolist(), group['value'].tolist()))
                        logger.debug(f"Timeseries {metric_name}: VRM HELPER used, {len(clean_df)} records")
            
            return {
                "data": client_data,
                "clients": client_names,
                "time_range": {"start": start_time, "end": end_time},
                "metric": metric_name,
                "aggregation": aggregation,
                "unit": ""
            }
            
        except Exception as e:
            import traceback
            logger.error(f"Error getting {metric_name} timeseries: {e}")
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail="Failed to get timeseries data")

    return router