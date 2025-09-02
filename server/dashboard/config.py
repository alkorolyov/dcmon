"""
Dashboard Configuration

Configurable thresholds and styling for the dashboard.
Clean, simplified configuration without backward compatibility.
"""

from typing import Dict, Any

# Metric Thresholds for Color Coding
# Format: [low_threshold, medium_threshold, high_threshold]
# Colors: blue (optimal) -> green (normal) -> yellow (warning) -> red (critical)
METRIC_THRESHOLDS = {
    # CPU and System
    'cpu_temp_celsius': [65, 75, 85],
    'cpu_usage_percent': [50, 70, 90],
    'memory_usage_percent': [60, 80, 90],
    'cpu_load_1m': [2, 4, 8],
    
    # GPU Metrics
    'gpu_temperature': [60, 70, 80],
    'gpu_fan_speed': [30, 60, 80],
    'gpu_power_draw': [200, 350, 420],
    
    # Storage
    'disk_usage_percent': [50, 70, 85],
    
    # VRM and IPMI
    'cpu_vrm_temp': [65, 80, 95],
    'dimm_temp_avg': [45, 60, 75],
    'nvme_wear_percent': [50, 80, 90],
}

def get_metric_status(metric_name: str, value: float) -> str:
    """
    Determine the status level of a metric based on configured thresholds.
    
    Args:
        metric_name: Name of the metric (e.g., 'cpu_usage_percent')
        value: Metric value to evaluate
        
    Returns:
        Status string: 'low', 'normal', 'high', or 'critical'
    """
    if not value or metric_name not in METRIC_THRESHOLDS:
        return 'no_data'
    
    thresholds = METRIC_THRESHOLDS[metric_name]
    
    if len(thresholds) == 3:
        # Three-threshold system (low, normal, high, critical)
        if value < thresholds[0]:
            return 'low'
        elif value < thresholds[1]:
            return 'normal'
        elif value < thresholds[2]:
            return 'high'
        else:
            return 'critical'
    
    return 'normal'

def format_metric_value(value: Any, format_type: str) -> str:
    """
    Format a metric value according to its type.
    
    Args:
        value: Raw metric value
        format_type: Type of formatting to apply
        
    Returns:
        Formatted string representation
    """
    if value is None or value == '':
        return '—'
    
    try:
        if format_type == "percentage":
            return f"{float(value):.0f}%"
        elif format_type == "temperature":
            return f"{float(value):.0f}°"
        elif format_type == "power":
            return f"{float(value):.0f}W"
        elif format_type == "frequency":
            return f"{float(value):.0f}MHz"
        else:
            return str(value)
    except (ValueError, TypeError):
        return '—'