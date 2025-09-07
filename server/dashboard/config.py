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
    'gpu_temperature': [50, 70, 80],
    'gpu_fan_speed': [30, 50, 80],
    'gpu_power_draw': [200, 350, 420],
    
    # Storage
    'disk_usage_percent': [50, 70, 85],
    
    # VRM and IPMI
    'cpu_vrm_temp': [65, 80, 95],
    'dimm_temp_avg': [45, 60, 75],
    'nvme_wear_percent': [50, 80, 90],
    
    # PSU Metrics
    'psu_temp_celsius': [40, 50, 60],
    'psu_input_power_watts': [800, 1600, 2000],
    'psu_fan_rpm': [2000, 5000, 8000],
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

def format_metric_value(value: Any, unit: str) -> str:
    """
    Format a metric value with proper rounding and unit.
    
    Args:
        value: Raw metric value
        unit: Unit string (e.g., "°", "%", "W")
        
    Returns:
        Formatted string representation with proper rounding
    """
    if value is None or value == '':
        return '—'
    
    try:
        # Convert to float for proper rounding
        num_val = float(value)
        
        # Round based on value magnitude for better readability
        if unit == "%":
            # Percentages: round to 1 decimal if < 10, else integer
            if num_val < 10:
                return f"{num_val:.1f}%"
            else:
                return f"{num_val:.0f}%"
        elif unit == "°":
            # Temperatures: always integer
            return f"{num_val:.0f}°"
        elif unit == "W":
            # Power: always integer 
            return f"{num_val:.0f}W"
        else:
            # Other units: round to 1 decimal if < 10, else integer
            if num_val < 10:
                return f"{num_val:.1f}{unit}"
            else:
                return f"{num_val:.0f}{unit}"
    except (ValueError, TypeError):
        return '—'