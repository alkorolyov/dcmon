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
except ImportError:
    from models import Client, MetricSeries, MetricPointsInt, MetricPointsFloat, Command

from .config import get_metric_status, format_metric_value, METRIC_THRESHOLDS

logger = logging.getLogger("dcmon.dashboard")


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
            }
            
            logger.debug(f"Dashboard data prepared: {len(dashboard_data)} sections")
            return dashboard_data
            
        except Exception as e:
            logger.error(f"Error generating dashboard data: {e}")
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
        
        # Get individual system metrics
        individual_metrics = ['cpu_usage_percent', 'memory_usage_percent', 'cpu_load_1m']
        for metric_name in individual_metrics:
            value = self._get_latest_metric_value(client_id, metric_name)
            if value is not None:
                latest_metrics[metric_name] = value
        
            
            
        # Get critical health metrics
        cpu_temp_single = self._get_cpu_temp_single(client_id)
        if cpu_temp_single is not None:
            latest_metrics['cpu_temp_single'] = cpu_temp_single
            
        vrm_temp_max = self._get_max_vrm_temp(client_id)
        if vrm_temp_max is not None:
            latest_metrics['vrm_temp_max'] = vrm_temp_max
            
        gpu_temp_max = self._get_max_gpu_temp(client_id)
        if gpu_temp_max is not None:
            latest_metrics['gpu_temp_max'] = gpu_temp_max
            
        gpu_power_max = self._get_max_gpu_power(client_id)
        if gpu_power_max is not None:
            latest_metrics['gpu_power_max'] = gpu_power_max
            
        gpu_limit_max = self._get_max_gpu_limit(client_id)
        if gpu_limit_max is not None:
            latest_metrics['gpu_limit_max'] = gpu_limit_max
            
        gpu_fan_max = self._get_max_gpu_fan(client_id)
        if gpu_fan_max is not None:
            latest_metrics['gpu_fan_max'] = gpu_fan_max
            
        disk_root_percent = self._get_disk_usage_percent(client_id, '/')
        if disk_root_percent is not None:
            latest_metrics['disk_root_percent'] = disk_root_percent
            
        disk_docker_percent = self._get_disk_usage_percent(client_id, '/var/lib/docker')
        if disk_docker_percent is not None:
            latest_metrics['disk_docker_percent'] = disk_docker_percent
            
        
        
        
        return latest_metrics
    
    def _get_latest_metric_value(self, client_id: int, metric_name: str) -> Optional[float]:
        """Get the latest value for a specific metric."""
        try:
            # Find the series for this metric
            series = MetricSeries.select().where(
                (MetricSeries.client == client_id) &
                (MetricSeries.metric_name == metric_name)
            ).first()
            
            if not series:
                return None
            
            # Try float points first, then int points
            latest_float = (MetricPointsFloat.select()
                           .where(MetricPointsFloat.series == series.id)
                           .order_by(MetricPointsFloat.timestamp.desc())
                           .first())
            
            if latest_float:
                return latest_float.value
            
            latest_int = (MetricPointsInt.select()
                         .where(MetricPointsInt.series == series.id)
                         .order_by(MetricPointsInt.timestamp.desc())
                         .first())
            
            if latest_int:
                return float(latest_int.value)
            
            return None
            
        except Exception as e:
            logger.debug(f"Error getting latest metric {metric_name} for client {client_id}: {e}")
            return None
    
    
    def _get_disk_usage_percent(self, client_id: int, mountpoint: str) -> Optional[float]:
        """Get disk usage percentage for a specific mountpoint."""
        try:
            # Get total bytes for this mountpoint
            total_series = MetricSeries.select().where(
                (MetricSeries.client == client_id) &
                (MetricSeries.metric_name == 'fs_total_bytes') &
                (MetricSeries.labels.contains(f'"mountpoint":"{mountpoint}"'))
            ).first()
            
            # Get used bytes for this mountpoint  
            used_series = MetricSeries.select().where(
                (MetricSeries.client == client_id) &
                (MetricSeries.metric_name == 'fs_used_bytes') &
                (MetricSeries.labels.contains(f'"mountpoint":"{mountpoint}"'))
            ).first()
            
            if not total_series or not used_series:
                return None
            
            # Get latest values
            total_point = (MetricPointsInt.select()
                          .where(MetricPointsInt.series == total_series.id)
                          .order_by(MetricPointsInt.timestamp.desc())
                          .first())
            
            used_point = (MetricPointsInt.select()
                         .where(MetricPointsInt.series == used_series.id)
                         .order_by(MetricPointsInt.timestamp.desc())
                         .first())
            
            if not total_point or not used_point or total_point.value == 0:
                return None
            
            # Calculate percentage
            usage_percent = (used_point.value / total_point.value) * 100
            return usage_percent
            
        except Exception as e:
            logger.debug(f"Error getting disk usage for {mountpoint} on client {client_id}: {e}")
            return None
    
    
    
    
    
    
    
    def _get_cpu_temp_single(self, client_id: int) -> Optional[float]:
        """Get CPU temperature from both Supermicro and AsRock sensors."""
        try:
            # Try both sensor naming conventions
            cpu_sensors = ['CPU Temp', 'TEMP_CPU']
            
            for sensor_name in cpu_sensors:
                series = MetricSeries.select().where(
                    (MetricSeries.client == client_id) &
                    (MetricSeries.metric_name == 'ipmi_temp_celsius') &
                    (MetricSeries.labels.contains(f'"sensor":"{sensor_name}"'))
                ).first()
                
                if series:
                    temp_point = (MetricPointsInt.select()
                                 .where(MetricPointsInt.series == series.id)
                                 .order_by(MetricPointsInt.timestamp.desc())
                                 .first())
                    
                    if temp_point:
                        return float(temp_point.value)
            
            return None
            
        except Exception as e:
            logger.debug(f"Error getting single CPU temperature for client {client_id}: {e}")
            return None
    
    
    
    def _get_max_vrm_temp(self, client_id: int) -> Optional[float]:
        """Get maximum VRM temperature across all VRM sensors."""
        try:
            vrm_sensors = ['CPU_VRM Temp', 'SOC_VRM Temp', 'VRMABCD Temp', 'VRMEFGH Temp']
            max_temp = None
            
            for sensor_name in vrm_sensors:
                series = MetricSeries.select().where(
                    (MetricSeries.client == client_id) &
                    (MetricSeries.metric_name == 'ipmi_temp_celsius') &
                    (MetricSeries.labels.contains(f'"sensor":"{sensor_name}"'))
                ).first()
                
                if series:
                    temp_point = (MetricPointsInt.select()
                                 .where(MetricPointsInt.series == series.id)
                                 .order_by(MetricPointsInt.timestamp.desc())
                                 .first())
                    
                    if temp_point:
                        temp_value = float(temp_point.value)
                        if max_temp is None or temp_value > max_temp:
                            max_temp = temp_value
            
            return max_temp
            
        except Exception as e:
            logger.debug(f"Error getting max VRM temperature for client {client_id}: {e}")
            return None
    
    def _get_max_gpu_temp(self, client_id: int) -> Optional[float]:
        """Get maximum GPU temperature across all GPUs."""
        try:
            gpu_series = list(MetricSeries.select().where(
                (MetricSeries.client == client_id) &
                (MetricSeries.metric_name == 'gpu_temperature')
            ))
            
            max_temp = None
            
            for series in gpu_series:
                temp_point = (MetricPointsInt.select()
                             .where(MetricPointsInt.series == series.id)
                             .order_by(MetricPointsInt.timestamp.desc())
                             .first())
                
                if temp_point:
                    temp_value = float(temp_point.value)
                    if max_temp is None or temp_value > max_temp:
                        max_temp = temp_value
            
            return max_temp
            
        except Exception as e:
            logger.debug(f"Error getting max GPU temperature for client {client_id}: {e}")
            return None
    
    def _get_max_gpu_power(self, client_id: int) -> Optional[float]:
        """Get maximum GPU power consumption across all GPUs."""
        try:
            power_series = list(MetricSeries.select().where(
                (MetricSeries.client == client_id) &
                (MetricSeries.metric_name == 'gpu_power_draw')
            ))
            
            max_power = None
            
            for series in power_series:
                power_point = (MetricPointsInt.select()
                              .where(MetricPointsInt.series == series.id)
                              .order_by(MetricPointsInt.timestamp.desc())
                              .first())
                
                if power_point:
                    power_value = float(power_point.value)
                    if max_power is None or power_value > max_power:
                        max_power = power_value
            
            return max_power
            
        except Exception as e:
            logger.debug(f"Error getting max GPU power for client {client_id}: {e}")
            return None
    
    def _get_max_gpu_limit(self, client_id: int) -> Optional[float]:
        """Get maximum GPU power limit across all GPUs."""
        try:
            limit_series = list(MetricSeries.select().where(
                (MetricSeries.client == client_id) &
                (MetricSeries.metric_name == 'gpu_power_limit')
            ))
            
            max_limit = None
            
            for series in limit_series:
                limit_point = (MetricPointsInt.select()
                              .where(MetricPointsInt.series == series.id)
                              .order_by(MetricPointsInt.timestamp.desc())
                              .first())
                
                if limit_point:
                    limit_value = float(limit_point.value)
                    if max_limit is None or limit_value > max_limit:
                        max_limit = limit_value
            
            return max_limit
            
        except Exception as e:
            logger.debug(f"Error getting max GPU power limit for client {client_id}: {e}")
            return None
    
    def _get_max_gpu_fan(self, client_id: int) -> Optional[float]:
        """Get maximum GPU fan speed percentage across all GPUs."""
        try:
            fan_series = list(MetricSeries.select().where(
                (MetricSeries.client == client_id) &
                (MetricSeries.metric_name == 'gpu_fan_speed')
            ))
            
            max_fan = None
            
            for series in fan_series:
                fan_point = (MetricPointsInt.select()
                            .where(MetricPointsInt.series == series.id)
                            .order_by(MetricPointsInt.timestamp.desc())
                            .first())
                
                if fan_point:
                    fan_value = float(fan_point.value)
                    if max_fan is None or fan_value > max_fan:
                        max_fan = fan_value
            
            return max_fan
            
        except Exception as e:
            logger.debug(f"Error getting max GPU fan speed for client {client_id}: {e}")
            return None
    
    
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