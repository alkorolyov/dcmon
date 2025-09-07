"""
Dashboard Controller

Main controller class that handles all dashboard data preparation.
All methods return Python data structures that are easily debuggable and testable.
"""

import time
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

# Support running as script or as package
try:
    from ..models import Client, MetricSeries, MetricPointsInt, MetricPointsFloat, Command
    from ..api.metric_queries import MetricQueryBuilder
except ImportError:
    from models import Client, MetricSeries, MetricPointsInt, MetricPointsFloat, Command
    from api.metric_queries import MetricQueryBuilder

from .config import get_metric_status, format_metric_value, METRIC_THRESHOLDS

logger = logging.getLogger("dcmon.dashboard")

# Smart table column configuration with direct MetricQueryBuilder parameter mapping
TABLE_COLUMNS = [
    # Temperature and hardware metrics first
    {
        "metric_name": "ipmi_temp_celsius",
        "label_filters": [{"sensor": "CPU Temp"}, {"sensor": "TEMP_CPU"}],
        "aggregation": "max",
        "header": "CPU°C", "unit": "°", "css_class": "col-cpu-temp"
    },
    
    # VRM temperature (max across all VRM sensors)
    {
        "metric_name": "ipmi_temp_celsius",
        "label_filters": [{"sensor": "CPU_VRM Temp"}, {"sensor": "SOC_VRM Temp"}, {"sensor": "VRMABCD Temp"}, {"sensor": "VRMEFGH Temp"}, {"sensor": "FSC_INDEX1"}],
        "aggregation": "max",
        "header": "VRM°C", "unit": "°", "css_class": "col-vrm-temp"
    },
    
    # NVME temperature (useful storage metric)
    {
        "metric_name": "nvme_temperature_celsius",
        "aggregation": "max",
        "header": "NVME°C", "unit": "°", "css_class": "col-nvme-temp"
    },
    
    # GPU metrics with aggregation
    {
        "metric_name": "gpu_temperature",
        "aggregation": "max",
        "header": "GPU°C", "unit": "°", "css_class": "col-gpu-temp"
    },
    {
        "metric_name": "gpu_power_draw",
        "aggregation": "max",
        "header": "GPU Power", "unit": "W", "css_class": "col-gpu-power"
    },
    {
        "metric_name": "gpu_power_limit",
        "aggregation": "max",
        "header": "GPU Limit", "unit": "W", "css_class": "col-gpu-limit", "no_threshold": True
    },
    {
        "metric_name": "gpu_fan_speed",
        "aggregation": "max",
        "header": "GPU Fan%", "unit": "%", "css_class": "col-gpu-fan"
    },
    
    # PSU metrics - power supply monitoring
    {
        "metric_name": ["psu_temp1_celsius", "psu_temp2_celsius"],
        "aggregation": "max",
        "threshold_type": "psu_temp_celsius",
        "header": "PSU°C", "unit": "°", "css_class": "col-psu-temp"
    },
    {
        "metric_name": "psu_input_power_watts",
        "aggregation": "sum",
        "header": "Power", "unit": "W", "css_class": "col-psu-power"
    },
    {
        "metric_name": ["psu_fan1_rpm", "psu_fan2_rpm"],
        "aggregation": "max",
        "threshold_type": "psu_fan_rpm",
        "header": "PSU Fan", "unit": "rpm", "css_class": "col-psu-fan"
    },
    
    # Usage metrics - typically single series per client
    {
        "metric_name": "cpu_usage_percent",
        "header": "CPU%", "unit": "%", "css_class": "col-cpu-usage"
    },
    {
        "metric_name": "memory_usage_percent",
        "header": "RAM%", "unit": "%", "css_class": "col-ram"
    },
    {
        "operation": "fraction",
        "metric_name": "disk_usage_percent",
        "numerator": {"metric_name": "fs_used_bytes", "label_filters": [{"mountpoint": "/"}]},
        "denominator": {"metric_name": "fs_total_bytes", "label_filters": [{"mountpoint": "/"}]},
        "multiply_by": 100,
        "header": "Root%", "unit": "%", "css_class": "col-disk-root"
    },
    {
        "operation": "fraction",
        "metric_name": "disk_usage_percent",
        "numerator": {"metric_name": "fs_used_bytes", "label_filters": [{"mountpoint": "/var/lib/docker"}]},
        "denominator": {"metric_name": "fs_total_bytes", "label_filters": [{"mountpoint": "/var/lib/docker"}]},
        "multiply_by": 100,
        "header": "Docker%", "unit": "%", "css_class": "col-disk-docker"
    },
]


class DashboardController:
    """
    Main dashboard controller - all dashboard logic in pure Python.
    
    This class centralizes all dashboard data preparation, making it easy for AI
    to understand, debug, and modify the dashboard behavior.
    """
    
    def __init__(self):
        pass
    
    def get_main_dashboard_data(self) -> Dict[str, Any]:
        """
        Get complete dashboard data structure.
        
        Returns a dictionary with all data needed to render the main dashboard.
        This makes it easy to debug what data is being passed to templates.
        """
        logger.debug("Generating main dashboard data")
        
        try:
            clients_data = self._get_client_status_data()
            dashboard_data = {
                "page_title": "dcmon Dashboard",
                "timestamp": int(time.time()),
                "clients": clients_data,
                "total_clients": len(clients_data),
                "online_clients": len([c for c in clients_data if c.get('status') == 'online']),
                "system_overview": self._get_system_overview_data(),
                "recent_alerts": self._get_recent_alerts(),
                "table_columns": TABLE_COLUMNS,
            }
            
            logger.debug(f"Dashboard data prepared: {len(dashboard_data)} sections")
            return dashboard_data
            
        except Exception as e:
            logger.error(f"Error generating dashboard data: {e}", exc_info=True)
            return {
                "page_title": "dcmon Dashboard - Error",
                "timestamp": int(time.time()),
                "error": str(e),
                "clients": [],
                "system_overview": {},
                "recent_alerts": []
            }
    
    def _get_client_status_data(self) -> List[Dict[str, Any]]:
        """Get client status information for the dashboard grid."""
        logger.debug("Fetching client status data")
        
        clients = []
        current_time = int(time.time())
        
        for client in Client.select().order_by(Client.hostname.asc()):
            # Determine if client is online (seen within last 5 minutes)
            is_online = (client.last_seen and 
                        (current_time - client.last_seen) < 300)
            
            # Get latest metrics summary
            latest_metrics = self._get_client_latest_metrics(client.id)
            
            client_data = {
                "id": client.id,
                "hostname": client.hostname,
                "machine_id": client.machine_id[:12] if client.machine_id else "unknown",
                "is_online": is_online,
                "last_seen": client.last_seen,
                "last_seen_human": self._format_time_ago(client.last_seen) if client.last_seen else "Never",
                "status": "online" if is_online else "offline",
                "latest_metrics": latest_metrics,
                    }
            
            clients.append(client_data)
        
        logger.debug(f"Processed {len(clients)} clients")
        
        # Prepare metric data for smart table rendering
        clients = self._prepare_client_metrics(clients)
        
        return clients
    
    def _get_client_latest_metrics(self, client_id: int) -> Dict[str, Any]:
        """Get the latest metrics for a specific client."""
        # Get series for this client
        series_ids = list(MetricSeries.select(MetricSeries.id).where(
            MetricSeries.client == client_id
        ))
        
        if not series_ids:
            return {}
        
        # Get latest metrics (both int and float)
        latest_metrics = {}
        
        # This method is now simplified since TABLE_COLUMNS handles all metric display
        # via centralized MetricQueryBuilder. Legacy individual metric functions removed.
        return {}
    
    
    
    
    def _get_system_overview_data(self) -> Dict[str, Any]:
        """Get system-wide overview statistics."""
        logger.debug("Generating system overview")
        
        total_clients = Client.select().count()
        online_clients = 0
        current_time = int(time.time())
        
        for client in Client.select():
            if client.last_seen and (current_time - client.last_seen) < 300:
                online_clients += 1
        
        # Get total metrics count
        total_int_metrics = MetricPointsInt.select().count()
        total_float_metrics = MetricPointsFloat.select().count()
        total_metrics = total_int_metrics + total_float_metrics
        
        # Get pending commands
        pending_commands = Command.select().where(Command.status == 'pending').count()
        
        return {
            "total_clients": total_clients,
            "online_clients": online_clients,
            "offline_clients": total_clients - online_clients,
            "total_metrics": total_metrics,
            "pending_commands": pending_commands,
        }
    
    def _get_recent_alerts(self) -> List[Dict[str, Any]]:
        """Get recent system alerts and warnings."""
        alerts = []
        
        # Check for offline clients
        current_time = int(time.time())
        for client in Client.select():
            if client.last_seen and (current_time - client.last_seen) > 300:  # 5 minutes
                time_offline = current_time - client.last_seen
                alerts.append({
                    "type": "warning",
                    "message": f"Client {client.hostname} has been offline for {self._format_duration(time_offline)}",
                    "timestamp": client.last_seen,
                    "client_id": client.id
                })
        
        # TODO: Add temperature, disk space, and other alerts
        
        # Sort by timestamp descending and limit to recent alerts
        alerts.sort(key=lambda x: x["timestamp"] or 0, reverse=True)
        return alerts[:10]  # Last 10 alerts
    
    
    def _format_time_ago(self, timestamp: int) -> str:
        """Format timestamp as human-readable time ago."""
        if not timestamp:
            return "Never"
        
        try:
            diff = int(time.time()) - timestamp
            if diff < 60:
                return f"{diff}s ago"
            elif diff < 3600:
                return f"{diff // 60}m ago"
            elif diff < 86400:
                return f"{diff // 3600}h ago"
            else:
                return f"{diff // 86400}d ago"
        except:
            return "Unknown"
    
    def _format_duration(self, seconds: int) -> str:
        """Format duration in seconds as human-readable string."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m"
        elif seconds < 86400:
            return f"{seconds // 3600}h"
        else:
            return f"{seconds // 86400}d"
    
    
    def get_latest_metric(self, client_id: int, column_config: Dict[str, Any]) -> Optional[float]:
        """
        Get latest metric value with support for operations (fraction, rate, sum_over_time).
        
        Uses zero parameter mapping for regular metrics and operation dispatch for calculated metrics.
        """
        try:
            operation = column_config.get("operation")
            
            if operation == "fraction":
                return self._calculate_fraction(client_id, column_config)
            elif operation == "rate":
                return self._calculate_rate(client_id, column_config)
            elif operation == "sum_over_time":
                return self._calculate_sum_over_time(client_id, column_config)
            else:
                # Regular metric - direct parameter pass-through to MetricQueryBuilder
                return MetricQueryBuilder.get_latest_metric_value(
                    client_id=client_id,
                    metric_name=column_config["metric_name"],
                    label_filters=column_config.get("label_filters"),
                    aggregation=column_config.get("aggregation")
                )
                    
        except Exception as e:
            logger.error(f"Error getting metric for client {client_id}: {e}", exc_info=True)
            return None
    
    def _calculate_fraction(self, client_id: int, column_config: Dict[str, Any]) -> Optional[float]:
        """
        Calculate fraction operation: (numerator / denominator) * multiplier.
        
        Uses single optimized query when possible to get both values at the same timestamp.
        """
        try:
            numerator_config = column_config["numerator"]
            denominator_config = column_config["denominator"]
            multiplier = column_config.get("multiply_by", 1)
            
            # Get numerator value
            numerator = MetricQueryBuilder.get_latest_metric_value(
                client_id=client_id,
                metric_name=numerator_config["metric_name"],
                label_filters=numerator_config.get("label_filters"),
                aggregation=numerator_config.get("aggregation")
            )
            
            # Get denominator value
            denominator = MetricQueryBuilder.get_latest_metric_value(
                client_id=client_id,
                metric_name=denominator_config["metric_name"],
                label_filters=denominator_config.get("label_filters"),
                aggregation=denominator_config.get("aggregation")
            )
            
            # Calculate fraction
            if numerator is not None and denominator is not None and denominator != 0:
                return (numerator / denominator) * multiplier
            
            return None
            
        except Exception as e:
            logger.error(f"Error calculating fraction for client {client_id}: {e}", exc_info=True)
            return None
    
    def _prepare_client_metrics(self, clients_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Prepare all metric data for each client using the smart table configuration.
        
        This keeps business logic in Python and makes templates pure presentation.
        """
        from .config import get_metric_status, format_metric_value
        
        for client in clients_data:
            client["metric_values"] = {}
            
            for col in TABLE_COLUMNS:
                value = self.get_latest_metric(client["id"], col)
                
                # Determine status
                if value is not None:
                    if col.get('neutral'):
                        status = 'neutral'
                    elif col.get('no_threshold'):
                        status = ''  # No special coloring, just normal table cell
                    else:
                        threshold_type = col.get('threshold_type', col["metric_name"])
                        status = get_metric_status(threshold_type, value)
                else:
                    status = 'no-data'
                
                # Store prepared data
                client["metric_values"][col["css_class"]] = {
                    "value": value,
                    "formatted": format_metric_value(value, col["unit"]) if value is not None else "—",
                    "status": status
                }
        
        return clients_data