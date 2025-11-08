"""
Label formatting and GPU mapping utilities.

Handles creating user-friendly labels from metric metadata
and maintaining consistent GPU numbering across metrics.
"""

import json
import logging
import re
from typing import Dict

try:
    from ...models import MetricSeries, MetricPoints
except ImportError:
    from models import MetricSeries, MetricPoints

logger = logging.getLogger("dcmon.server")

# Class variable to maintain consistent GPU numbering across all metrics
_gpu_mapping = {}


def create_friendly_label(labels_dict: dict, metric_name: str) -> str:
    """
    Create user-friendly labels for metrics.

    Args:
        labels_dict: Dictionary of metric labels
        metric_name: Name of the metric

    Returns:
        Friendly label string
    """
    global _gpu_mapping

    # Handle GPU labels - map PCI addresses and indices to sequential GPU1, GPU2, etc
    if 'bus_id' in labels_dict:
        # Handle PCI addresses like "01:00.0", "C1:00.0" -> GPU1, GPU2, etc
        bus_id = labels_dict['bus_id']

        # Check if we already have this bus_id mapped
        if bus_id not in _gpu_mapping:
            # Assign the next available GPU number
            gpu_count = len(_gpu_mapping) + 1
            _gpu_mapping[bus_id] = gpu_count

        return f"GPU{_gpu_mapping[bus_id]}"

    elif 'gpu_index' in labels_dict:
        gpu_index = labels_dict['gpu_index']
        if gpu_index not in _gpu_mapping:
            gpu_count = len(_gpu_mapping) + 1
            _gpu_mapping[gpu_index] = gpu_count
        return f"GPU{_gpu_mapping[gpu_index]}"

    elif 'device' in labels_dict and ('gpu' in metric_name or 'utilization' in metric_name):
        # Handle device names like "card0" -> GPU1
        device = labels_dict['device']
        card_match = re.search(r'card(\d+)', device)
        if card_match:
            card_num = card_match.group(1)
            if card_num not in _gpu_mapping:
                gpu_count = len(_gpu_mapping) + 1
                _gpu_mapping[card_num] = gpu_count
            return f"GPU{_gpu_mapping[card_num]}"

        # Remove /dev/ prefix if present
        if device.startswith('/dev/'):
            device = device[5:]

        # Map other device names consistently
        if device not in _gpu_mapping:
            gpu_count = len(_gpu_mapping) + 1
            _gpu_mapping[device] = gpu_count
        return f"GPU{_gpu_mapping[device]}"

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
            label_id = create_friendly_label(labels_dict, metric_name)

            # Get latest value for this series
            latest_value = None
            latest_point = (MetricPoints.select()
                          .where(MetricPoints.series == series.id)
                          .order_by(MetricPoints.timestamp.desc())
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
