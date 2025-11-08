#!/usr/bin/env python3
"""
Template Helpers for dcmon Dashboard
"""

import time


def format_datetime(timestamp):
    """Format timestamp as full datetime string."""
    if not timestamp:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    except:
        return str(timestamp)


def format_time(timestamp):
    """Format timestamp as time only."""
    if not timestamp:
        return ""
    try:
        return time.strftime("%H:%M:%S", time.localtime(timestamp))
    except:
        return str(timestamp)


def format_time_ago(timestamp):
    """Format timestamp as relative time (e.g., '5m ago')."""
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


def format_bytes(bytes_value):
    """Format bytes value with appropriate unit."""
    if not bytes_value:
        return "0 B"
    try:
        bytes_val = float(bytes_value)
        if bytes_val < 1024:
            return f"{bytes_val:.0f}B"
        elif bytes_val < 1024**2:
            return f"{bytes_val/1024:.1f}KB"
        elif bytes_val < 1024**3:
            return f"{bytes_val/(1024**2):.1f}MB"
        else:
            return f"{bytes_val/(1024**3):.1f}GB"
    except:
        return str(bytes_value)


def format_uptime_long(seconds):
    """Format uptime in seconds as human readable string."""
    if not seconds:
        return "Unknown"
    try:
        seconds = int(seconds)
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        if days > 0:
            return f"{days} days, {hours} hours"
        elif hours > 0:
            return f"{hours} hours, {minutes} minutes"
        else:
            return f"{minutes} minutes"
    except:
        return "Unknown"


def format_elapsed_time(seconds):
    """Format elapsed time duration with optimal precision for performance logs."""
    if not seconds:
        return "0ms"
    try:
        if seconds < 1.0:
            return f"{int(seconds * 1000)}ms"
        elif seconds < 10:
            return f"{seconds:.1f}s" 
        elif seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"
    except:
        return str(seconds)


def get_metric_status_helper(metric_name, value):
    """Template helper for getting metric status class."""
    try:
        from dashboard.config import get_metric_status
        return get_metric_status(metric_name, float(value) if value else 0)
    except:
        return 'no_data'


def setup_template_filters(templates):
    """Setup all template filters in Jinja2 environment."""
    templates.env.filters['format_datetime'] = format_datetime
    templates.env.filters['format_time'] = format_time
    templates.env.filters['format_time_ago'] = format_time_ago
    templates.env.filters['format_bytes'] = format_bytes
    templates.env.filters['format_uptime_long'] = format_uptime_long
    templates.env.globals['get_metric_status'] = get_metric_status_helper