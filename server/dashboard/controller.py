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
    from ..models import Client, MetricSeries, MetricPointsInt, MetricPointsFloat, LogEntry
    from ..api.metric_queries import MetricQueryBuilder, CPU_SENSORS, VRM_SENSORS
    from ..web.template_helpers import format_bytes
except ImportError:
    from models import Client, MetricSeries, MetricPointsInt, MetricPointsFloat, LogEntry
    from api.metric_queries import MetricQueryBuilder, CPU_SENSORS, VRM_SENSORS
    from web.template_helpers import format_bytes

from .config import get_metric_status, format_metric_value, METRIC_THRESHOLDS

logger = logging.getLogger("dcmon.dashboard")

# Smart table column configuration with direct MetricQueryBuilder parameter mapping
TABLE_COLUMNS = [
    # Temperature and hardware metrics first - use centralized sensor mappings
    {
        "metric_name": "ipmi_temp_celsius",
        "label_filters": CPU_SENSORS,
        "aggregation": "max",
        "header": "CPU°C", "unit": "°", "css_class": "col-cpu-temp"
    },
    
    # VRM temperature (max across all VRM sensors)
    {
        "metric_name": "ipmi_temp_celsius",
        "label_filters": VRM_SENSORS,
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
        
        return {
            "total_clients": total_clients,
            "online_clients": online_clients,
            "offline_clients": total_clients - online_clients,
            "total_metrics": total_metrics,
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
            # Check for operations
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
    
    def _calculate_rate(self, client_id: int, column_config: Dict[str, Any]) -> Optional[float]:
        """
        Calculate rate operation: (current_value - previous_value) / time_interval.
        
        Used for counter-based metrics like network bytes to get bytes/second.
        """
        try:
            metric_name = column_config["metric_name"]
            label_filters = column_config.get("label_filters")
            aggregation = column_config.get("aggregation", "max")
            time_window = column_config.get("time_window", 300)  # Default 5 minutes
            
            # Get current time
            current_time = int(time.time())
            
            # Get current value (latest)
            current_value = MetricQueryBuilder.get_latest_metric_value(
                client_id=client_id,
                metric_name=metric_name,
                label_filters=label_filters,
                aggregation=aggregation
            )
            
            if current_value is None:
                return None
                
            # Get previous value from time_window seconds ago
            from api.metric_queries import MetricQueryBuilder
            previous_data = MetricQueryBuilder.get_timeseries_data(
                metric_name=metric_name,
                start_time=current_time - time_window - 60,  # Extra buffer for data availability
                end_time=current_time - time_window + 60,    # Allow some tolerance
                client_ids=[client_id],
                aggregation=aggregation,
                label_filters=label_filters
            )
            
            if not previous_data or len(previous_data) == 0:
                return None
            
            # Find the closest previous value
            previous_value = None
            previous_timestamp = None
            
            for timestamp, values in previous_data:
                if values and len(values) > 0:
                    previous_value = values[0]  # Take first series value
                    previous_timestamp = timestamp
                    break
            
            if previous_value is None or previous_timestamp is None:
                return None
            
            # Calculate rate: (current - previous) / time_elapsed
            time_elapsed = current_time - previous_timestamp
            if time_elapsed <= 0:
                return None
                
            # Handle counter resets (current < previous means counter reset)
            if current_value < previous_value:
                # For now, just return current value as rate (simple approach)
                # Could be enhanced to handle 32/64-bit counter wraparounds
                return current_value / time_elapsed
            
            rate = (current_value - previous_value) / time_elapsed
            return max(0, rate)  # Ensure non-negative rate
            
        except Exception as e:
            logger.error(f"Error calculating rate for client {client_id}: {e}", exc_info=True)
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
    
    def get_client_detail_data(self, client_id: int) -> Dict[str, Any]:
        """Get detailed client information for modal display."""
        try:
            # Get client basic info
            client = Client.get_by_id(client_id)
            current_time = int(time.time())
            is_online = (client.last_seen and (current_time - client.last_seen) < 300)
            
            # Get all metrics for this client using single batch query
            from api.metric_queries import MetricQueryBuilder
            raw_metrics = MetricQueryBuilder.get_all_latest_metrics_for_client(client_id)
            
            # Organize metrics by hardware device for detailed display
            detailed_metrics = {
                "gpu_table": [],   # List of GPU devices for table format
                "psu_table": [],   # List of PSU devices for table format  
                "storage_table": [], # List of storage devices for table format
                "network": {},     # eno1: {tx_bytes: 1.2GB, rx_bytes: 800MB} - keep compact
                "system": {}       # Motherboard sensors, CPU, system fans not tied to devices
            }
            
            # Temporary storage for building table rows
            gpu_devices = {}
            psu_devices = {}
            storage_devices = {}
            
            # Process raw metrics into device-focused structure
            for metric_name, label_values in raw_metrics.items():
                for label, value in label_values.items():
                    metric_info = {
                        "value": value,
                        "formatted": self._format_detailed_metric(metric_name, value),
                        "status": self._get_metric_status_for_device(metric_name, value),
                        "metric_name": metric_name
                    }
                    
                    # Extract device identifier and metric type
                    device_id, metric_type = self._categorize_by_device(label, metric_name)
                    
                    # Group by device type for table format
                    if device_id.startswith('GPU'):
                        if device_id not in gpu_devices:
                            gpu_devices[device_id] = {"device": device_id}
                        gpu_devices[device_id][metric_type] = metric_info
                        
                    elif device_id.startswith('PSU'):
                        if device_id not in psu_devices:
                            psu_devices[device_id] = {"device": device_id}
                        psu_devices[device_id][metric_type] = metric_info
                        
                    elif self._is_network_device(label, metric_name):
                        if device_id not in detailed_metrics["network"]:
                            detailed_metrics["network"][device_id] = {}
                        detailed_metrics["network"][device_id][metric_type] = metric_info
                        
                    elif self._is_storage_device(label, metric_name):
                        if device_id not in storage_devices:
                            storage_devices[device_id] = {"device": device_id}
                        storage_devices[device_id][metric_type] = metric_info
                        
                    else:
                        # System-level sensors (CPU temp, motherboard sensors, etc.)
                        # Don't use "default" labels - use metric name directly
                        if label == "default" or not label or label.strip() == "":
                            display_name = self._get_readable_metric_name(metric_name, metric_type)
                        else:
                            display_name = f"{label}"
                        detailed_metrics["system"][display_name] = metric_info
            
            # Convert device dictionaries to sorted table lists
            detailed_metrics["gpu_table"] = [gpu_devices[gpu] for gpu in sorted(gpu_devices.keys())]
            detailed_metrics["psu_table"] = [psu_devices[psu] for psu in sorted(psu_devices.keys())]
            detailed_metrics["storage_table"] = [storage_devices[storage] for storage in sorted(storage_devices.keys())]
            
            # Also keep original aggregated metrics for compatibility
            all_metrics = {}
            for col in TABLE_COLUMNS:
                value = self.get_latest_metric(client_id, col)
                if value is not None:
                    all_metrics[col["header"]] = {
                        "value": value,
                        "formatted": format_metric_value(value, col["unit"]),
                        "status": get_metric_status(col.get('threshold_type', col["metric_name"]), value) if not col.get('no_threshold') else ''
                    }
            
            # Get hardware information from client record
            hardware_info = {
                "motherboard": client.mdb_name or "Unknown",
                "cpu": client.cpu_name or "Unknown",
                "cpu_cores": client.cpu_cores or 0,
                "gpu": client.gpu_name or "Unknown", 
                "gpu_count": client.gpu_count or 0,
                "ram_gb": client.ram_gb or 0,
                "drives": client.drives or [],
                "vast_machine_id": client.vast_machine_id,
                "vast_port_range": client.vast_port_range,
                "full_machine_id": client.machine_id
            }
            
            # Get log counts and sources available for this client
            log_counts = LogEntry.get_log_counts_by_source(client_id)
            recent_log_counts = LogEntry.get_log_counts_by_source(client_id, current_time - 3600)  # Last hour
            
            # Available log sources for this client
            available_log_sources = []
            for source in ['journal', 'syslog', 'dmesg', 'vast']:
                total_count = log_counts.get(source, 0)
                recent_count = recent_log_counts.get(source, 0)
                if total_count > 0:
                    available_log_sources.append({
                        'source': source,
                        'display_name': source.title(),
                        'total_count': total_count,
                        'recent_count': recent_count
                    })
            
            return {
                "client_id": client_id,
                "hostname": client.hostname,
                "machine_id": client.machine_id[:12] if client.machine_id else "unknown",
                "is_online": is_online,
                "status": "online" if is_online else "offline",
                "last_seen": client.last_seen,
                "last_seen_human": self._format_time_ago(client.last_seen) if client.last_seen else "Never",
                "all_metrics": all_metrics,  # Keep for compatibility
                "detailed_metrics": detailed_metrics,  # New detailed breakdown
                "hardware_info": hardware_info,  # New hardware information
                "log_sources": available_log_sources,
                "timestamp": current_time
            }
            
        except Exception as e:
            logger.error(f"Error getting client detail data for client {client_id}: {e}", exc_info=True)
            return {
                "client_id": client_id,
                "error": str(e),
                "timestamp": int(time.time())
            }
    
    def get_client_logs(self, client_id: int, log_source: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent logs for a specific client and log source."""
        try:
            logs = LogEntry.get_recent_logs_by_source(client_id, log_source, limit)
            
            formatted_logs = []
            for log in logs:
                formatted_logs.append({
                    "timestamp": log.log_timestamp,
                    "timestamp_human": self._format_timestamp_human(log.log_timestamp),
                    "content": log.content,
                    "severity": log.severity,
                    "severity_class": self._get_severity_class(log.severity)
                })
            
            return formatted_logs
            
        except Exception as e:
            logger.error(f"Error getting logs for client {client_id}, source {log_source}: {e}", exc_info=True)
            return []
    
    def _format_timestamp_human(self, timestamp: int) -> str:
        """Format timestamp as human-readable date/time."""
        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%H:%M:%S")
        except:
            return "Unknown"
    
    def _format_detailed_metric(self, metric_name: str, value: float) -> str:
        """Format metric value with appropriate precision and unit."""
        
        # Handle all byte metrics - network, storage, filesystem
        if "bytes" in metric_name or "fs_" in metric_name:
            return format_bytes(value)
                
        # Handle RPM values - should show RPM not percentage  
        if "rpm" in metric_name or ("fan" in metric_name and "psu" in metric_name):
            return f"{value:.0f} RPM"
            
        # Handle voltage values
        if "voltage" in metric_name or "volt" in metric_name:
            return f"{value:.2f}V"
            
        # Handle percentage values (GPU fans, utilization, usage, wear level)
        if ("utilization" in metric_name or "usage" in metric_name or 
            ("fan" in metric_name and "gpu" in metric_name) or "wear" in metric_name):
            if "wear" in metric_name:
                return f"{value:.1f}%"  # More precision for wear level
            else:
                return f"{value:.0f}%"
            
        # Handle clock speeds
        if "clock" in metric_name:
            if value >= 1000:
                return f"{value/1000:.1f} GHz"
            else:
                return f"{value:.0f} MHz"
        
        # Handle memory sizes
        if "memory" in metric_name and "bytes" not in metric_name:
            return format_bytes(value * 1024 * 1024)  # Convert MB to bytes for formatting
            
        # Handle temperatures
        if "temp" in metric_name or "temperature" in metric_name:
            return format_metric_value(value, "°")
            
        # Handle power metrics
        if "power" in metric_name or "watts" in metric_name:
            return format_metric_value(value, "W")
        
        # Default fallback - just return the value with basic formatting
        return f"{value:.1f}" if value < 10 else f"{value:.0f}"
    
    def _get_severity_class(self, severity: str) -> str:
        """Get CSS class for log severity."""
        severity_map = {
            "ERROR": "severity-error",
            "WARN": "severity-warning", 
            "WARNING": "severity-warning",
            "INFO": "severity-info",
            "DEBUG": "severity-debug"
        }
        return severity_map.get(severity.upper(), "severity-info")
    
    def _categorize_by_device(self, label: str, metric_name: str) -> tuple[str, str]:
        """Extract device identifier and metric type from label and metric name."""
        import re
        
        # GPU devices - already mapped to GPU1, GPU2, etc.
        if label.startswith('GPU'):
            device_id = label  # GPU1, GPU2, etc.
            if "temp" in metric_name:
                metric_type = "Temperature"
            elif "fan" in metric_name:
                metric_type = "Fan Speed"
            elif "power" in metric_name:
                metric_type = "Power Draw"
            elif "utilization" in metric_name:
                metric_type = "Utilization"
            elif "memory" in metric_name:
                metric_type = "Memory"
            elif "clock" in metric_name:
                metric_type = "Clock Speed"
            else:
                metric_type = metric_name.replace('gpu_', '').replace('_', ' ').title()
            return device_id, metric_type
            
        # PSU devices
        elif label.startswith('PSU'):
            device_id = label  # PSU1, PSU2, etc.
            if "power" in metric_name or "watts" in metric_name:
                metric_type = "Power Input"
            elif "fan" in metric_name or "rpm" in metric_name:
                metric_type = "Fan Speed"
            elif "temp" in metric_name:
                metric_type = "Temperature"
            elif "voltage" in metric_name:
                metric_type = "Voltage"
            else:
                metric_type = metric_name.replace('psu_', '').replace('_', ' ').title()
            return device_id, metric_type
            
        # Network interfaces
        elif self._is_network_device(label, metric_name):
            # Extract interface name (eno1, eth0, etc.)
            device_id = label
            if "transmit" in metric_name or "tx" in metric_name:
                metric_type = "Transmit"
            elif "receive" in metric_name or "rx" in metric_name:
                metric_type = "Receive"
            else:
                metric_type = metric_name.replace('network_', '').replace('_', ' ').title()
            return device_id, metric_type
            
        # Storage devices
        elif self._is_storage_device(label, metric_name):
            # Extract device name (nvme0n1, sda1, etc.) or mount point (root, docker)
            device_id = label
            if "fs_" in metric_name:
                if "used" in metric_name:
                    metric_type = "Used Space"
                elif "free" in metric_name or "avail" in metric_name:
                    metric_type = "Free Space"
                elif "size" in metric_name:
                    metric_type = "Total Size"
                else:
                    metric_type = metric_name.replace('fs_', '').replace('_', ' ').title()
            elif "nvme_" in metric_name:
                if "wear" in metric_name:
                    metric_type = "Wear Level"
                elif "temp" in metric_name:
                    metric_type = "Temperature"
                else:
                    metric_type = metric_name.replace('nvme_', '').replace('_', ' ').title()
            else:
                metric_type = metric_name.replace('disk_', '').replace('_', ' ').title()
            return device_id, metric_type
            
        # Default fallback
        else:
            return label, metric_name.replace('_', ' ').title()
    
    def _get_readable_metric_name(self, metric_name: str, metric_type: str) -> str:
        """Convert metric names to readable display names when labels are missing."""
        # Handle filesystem metrics  
        if "fs_" in metric_name:
            if "used" in metric_name:
                return "Filesystem Used"
            elif "free" in metric_name or "avail" in metric_name:
                return "Filesystem Free" 
            elif "size" in metric_name:
                return "Filesystem Size"
            else:
                return f"Filesystem {metric_name.replace('fs_', '').replace('_', ' ').title()}"
        
        # Handle memory metrics
        elif "memory_" in metric_name:
            if "used" in metric_name:
                return "Memory Used"
            elif "free" in metric_name:
                return "Memory Free"
            elif "total" in metric_name:
                return "Memory Total"
            elif "percent" in metric_name:
                return "Memory Usage"
            else:
                return f"Memory {metric_name.replace('memory_', '').replace('_', ' ').title()}"
        
        # Handle CPU metrics
        elif "cpu_" in metric_name:
            if "usage" in metric_name:
                return "CPU Usage"
            elif "load" in metric_name:
                return "CPU Load"
            elif "temp" in metric_name:
                return "CPU Temperature"
            else:
                return f"CPU {metric_name.replace('cpu_', '').replace('_', ' ').title()}"
        
        # Handle network metrics
        elif "network_" in metric_name:
            if "bytes" in metric_name:
                if "tx" in metric_name or "transmit" in metric_name:
                    return "Network TX"
                elif "rx" in metric_name or "receive" in metric_name:
                    return "Network RX"
                else:
                    return "Network Traffic"
            else:
                return f"Network {metric_name.replace('network_', '').replace('_', ' ').title()}"
        
        # Handle disk/storage metrics
        elif "disk_" in metric_name:
            if "usage" in metric_name:
                return "Disk Usage"
            else:
                return f"Disk {metric_name.replace('disk_', '').replace('_', ' ').title()}"
        
        # Handle node/system metrics
        elif "node_" in metric_name:
            return metric_name.replace('node_', '').replace('_', ' ').title()
        
        # Use metric_type if available, otherwise clean up metric_name
        else:
            if metric_type and metric_type != metric_name:
                return metric_type
            else:
                return metric_name.replace('_', ' ').title()
    
    def _is_network_device(self, label: str, metric_name: str) -> bool:
        """Check if this is a network device metric."""
        network_patterns = ['eno', 'eth', 'wlan', 'lo', 'bond']
        network_metrics = ['network_', 'transmit', 'receive', 'tx_', 'rx_']
        
        # Check if label looks like a network interface
        label_is_network = any(label.startswith(pattern) for pattern in network_patterns)
        
        # Check if metric name suggests network data
        metric_is_network = any(pattern in metric_name for pattern in network_metrics)
        
        return label_is_network or metric_is_network
    
    def _is_storage_device(self, label: str, metric_name: str) -> bool:
        """Check if this is a storage device metric."""
        storage_patterns = ['nvme', 'sda', 'sdb', 'root', 'docker', '/']
        storage_metrics = ['fs_', 'disk_', 'nvme_']
        
        # Check if label looks like a storage device or mount point
        label_is_storage = any(pattern in label.lower() for pattern in storage_patterns)
        
        # Check if metric name suggests storage data
        metric_is_storage = any(pattern in metric_name for pattern in storage_metrics)
        
        return label_is_storage or metric_is_storage
    
    def _get_metric_status_for_device(self, metric_name: str, value: float) -> str:
        """Get status class for device metrics using dashboard thresholds."""
        # Map device metric names to dashboard threshold keys
        threshold_mapping = {
            # GPU metrics
            'gpu_temperature': 'gpu_temperature',
            'gpu_fan_speed': 'gpu_fan_speed', 
            'gpu_power_draw': 'gpu_power_draw',
            # Temperature metrics (IPMI, system)
            'ipmi_temp_celsius': 'cpu_temp_celsius',
            # PSU metrics  
            'psu_input_power_watts': 'psu_input_power_watts',
            'psu_fan_rpm': 'psu_fan_rpm',
            'psu_temp_celsius': 'psu_temp_celsius',
            # Storage metrics
            'fs_used_percent': 'disk_usage_percent',
            'nvme_wear_percent': 'nvme_wear_percent',
            # System metrics
            'cpu_usage_percent': 'cpu_usage_percent',
            'memory_usage_percent': 'memory_usage_percent',
        }
        
        # Get the appropriate threshold key
        threshold_key = threshold_mapping.get(metric_name, metric_name)
        
        # Use the dashboard config function
        return get_metric_status(threshold_key, value)