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
    from ...models import Client, MetricSeries, MetricPoints, LogEntry
    from ..schemas import MetricsBatchRequest
    from ..dependencies import AuthDependencies
    from ..queries import MetricQueryBuilder
except ImportError:
    from models import Client, MetricSeries, MetricPoints, LogEntry
    from api.schemas import MetricsBatchRequest
    from api.dependencies import AuthDependencies
    from api.queries import MetricQueryBuilder

logger = logging.getLogger("dcmon.server")


def create_metrics_routes(auth_deps: AuthDependencies) -> APIRouter:
    """Create metrics-related routes."""
    router = APIRouter()

    @router.post("/api/metrics")
    def submit_metrics(body: MetricsBatchRequest, client: Client = Depends(auth_deps.require_client_auth)):
        """Submit metrics batch from client."""
        now = int(time.time())
        metric_points = []  # All metrics stored as float per architecture decision

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

            # Store all metrics as float (architecture decision)
            metric_points.append({
                "series": series.id,
                "timestamp": m.timestamp,
                "sent_at": now,
                "value": float(m.value)
            })

        # Bulk insert points (all as float)
        inserted_total = 0
        if metric_points:
            inserted = MetricPoints.insert_many(metric_points).on_conflict_ignore().execute()
            inserted_total += int(inserted or 0)

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

        # Query metric points (all metrics stored as float)
        points_query = MetricPoints.select().where(MetricPoints.series.in_(series_ids))
        if start:
            points_query = points_query.where(MetricPoints.timestamp >= start)
        if end:
            points_query = points_query.where(MetricPoints.timestamp <= end)
        points_query = points_query.order_by(MetricPoints.timestamp.desc()).limit(limit)

        for point in points_query:
            series = next(s for s in series_list if s.id == point.series.id)
            out.append({
                "client_id": series.client.id,
                "timestamp": point.timestamp,
                "metric_name": series.metric_name,
                "value_float": point.value,
                "value_int": None,  # Legacy compatibility
                "labels": json.loads(series.labels) if series.labels else None,
            })

        return {"metrics": out}

    @router.get("/api/timeseries/{metric_name}/rate")
    def get_rate_timeseries(
        metric_name: str,
        seconds: int = Query(86400),  # Default 24 hours
        client_ids: Optional[List[int]] = Query(None),
        active_only: bool = Query(True),
        since_timestamp: Optional[int] = Query(None),
        until_timestamp: Optional[int] = Query(None),
        labels: Optional[str] = Query(None),  # JSON string of label filters
        aggregation: str = Query("sum"),
        rate_window: int = Query(5),  # Rate window in minutes
    ):
        """
        Get rate calculations for counter metrics.
        Dedicated endpoint for rate calculations with clean separation.
        """
        try:
            # Time range calculation
            end_time = int(time.time())
            
            if since_timestamp is not None:
                start_time = since_timestamp
                if until_timestamp is not None:
                    end_time = until_timestamp
            else:
                start_time = end_time - seconds
            
            # Parse metric names
            metric_names = [name.strip() for name in metric_name.split(',')]
            
            # Parse label filters if provided
            label_filters = None
            if labels:
                try:
                    import json
                    label_filters = json.loads(labels)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Invalid label filters JSON: {labels}")
            
            # Use the rate calculation function  
            from ..queries import MetricQueryBuilder
            df = MetricQueryBuilder.get_rate_timeseries(
                metric_name=metric_names,
                start_time=start_time,
                end_time=end_time,
                client_ids=client_ids,
                label_filters=label_filters,
                aggregation=aggregation,
                rate_window_minutes=rate_window,
                active_only=active_only
            )
            
            # Convert DataFrame to API format using vectorized operations
            if not df.empty:
                # Convert DataFrame directly to grouped JSON structure
                client_names = df.groupby('client_id')['client_name'].first().to_dict()
                
                # Vectorized groupby to create client data
                client_data = {}
                for client_id, group in df.groupby('client_id'):
                    client_data[int(client_id)] = group[['timestamp', 'value']].to_dict('records')
                
                return {
                    "data": client_data,
                    "clients": {int(k): v for k, v in client_names.items()},
                    "time_range": {"start": start_time, "end": end_time},
                    "metric": metric_name,
                    "aggregation": aggregation,
                    "unit": "rate",
                    "rate_window_minutes": rate_window
                }
            else:
                return {
                    "data": {},
                    "clients": {},
                    "time_range": {"start": start_time, "end": end_time},
                    "metric": metric_name,
                    "aggregation": aggregation,
                    "unit": "rate",
                    "rate_window_minutes": rate_window
                }
                
        except Exception as e:
            logger.error(f"Error in rate timeseries endpoint: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/timeseries/{metric_name}")
    def get_timeseries(
        metric_name: str,
        seconds: int = Query(86400),  # Default 24 hours = 86400 seconds
        client_ids: Optional[List[int]] = Query(None),
        active_only: bool = Query(True),  # Default to active clients only
        since_timestamp: Optional[int] = Query(None),  # For incremental queries
        until_timestamp: Optional[int] = Query(None),  # For gap-filling queries
        aggregation: str = Query("max", pattern="^(max|min|avg|sum|raw)$"),
        labels: Optional[str] = Query(None),  # JSON string of label filters
        admin_auth: bool = Depends(auth_deps.require_admin_auth)
    ):
        """
        General-purpose timeseries endpoint for dashboard charts.
        Uses Basic Auth authentication compatible with dashboard.
        """
        try:
            # Calculate time range
            end_time = int(time.time())
            
            # Use incremental timestamps if provided, otherwise use seconds range
            if since_timestamp is not None:
                start_time = since_timestamp
                if until_timestamp is not None:
                    end_time = until_timestamp
            else:
                start_time = end_time - seconds
            
            # Parse metric names
            metric_names = [name.strip() for name in metric_name.split(',')]
            
            # Create label filters from JSON labels parameter
            label_filters = None
            if labels:
                try:
                    label_filters = json.loads(labels)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Invalid label filters JSON: {labels}")
            
            # Use the clean get_timeseries_data function
            from ..queries import MetricQueryBuilder
            df = MetricQueryBuilder.get_timeseries_data(
                metric_name=metric_names,
                start_time=start_time,
                end_time=end_time,
                client_ids=client_ids,
                label_filters=label_filters,
                aggregation=aggregation
            )
            
            # Convert DataFrame to API format using vectorized operations
            if not df.empty:
                # Convert DataFrame directly to grouped JSON structure
                client_names = df.groupby('client_id')['client_name'].first().to_dict()
                
                # Vectorized groupby to create client data
                client_data = {}
                for client_id, group in df.groupby('client_id'):
                    client_data[int(client_id)] = group[['timestamp', 'value']].to_dict('records')
                
                return {
                    "data": client_data,
                    "clients": {int(k): v for k, v in client_names.items()},
                    "time_range": {"start": start_time, "end": end_time},
                    "metric": metric_name,
                    "aggregation": aggregation,
                    "unit": ""
                }
            else:
                return {
                    "data": {},
                    "clients": {},
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