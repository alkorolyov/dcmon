"""
Device categorization rules using table-driven approach.

Replaces complex if/elif chains with declarative lookup tables.
This makes it easy to add new device types and metric patterns.
"""

from typing import Tuple, Callable, List

# Device categorization rules
# Format: (label_prefix, metric_contains, metric_type, device_extractor)
DEVICE_RULES = [
    # GPU devices
    ('GPU', 'temp', 'Temperature', lambda l: l),
    ('GPU', 'fan', 'Fan Speed', lambda l: l),
    ('GPU', 'power', 'Power Draw', lambda l: l),
    ('GPU', 'utilization', 'Utilization', lambda l: l),
    ('GPU', 'memory', 'Memory', lambda l: l),
    ('GPU', 'clock', 'Clock Speed', lambda l: l),

    # PSU devices
    ('PSU', 'power', 'Power Input', lambda l: l),
    ('PSU', 'watts', 'Power Input', lambda l: l),
    ('PSU', 'fan', 'Fan Speed', lambda l: l),
    ('PSU', 'rpm', 'Fan Speed', lambda l: l),
    ('PSU', 'temp', 'Temperature', lambda l: l),
    ('PSU', 'voltage', 'Voltage', lambda l: l),
]

# Network device patterns
NETWORK_PATTERNS = ['eno', 'eth', 'wlan', 'lo', 'bond']
NETWORK_METRIC_KEYWORDS = ['network_', 'transmit', 'receive', 'tx_', 'rx_']

# Storage device patterns
STORAGE_PATTERNS = ['nvme', 'sda', 'sdb', 'root', 'docker', '/']
STORAGE_METRIC_KEYWORDS = ['fs_', 'disk_', 'nvme_']


def _is_network_device(label: str, metric_name: str) -> bool:
    """Check if this is a network device metric."""
    # Check if label looks like a network interface
    label_lower = label.lower()
    if any(pattern in label_lower for pattern in NETWORK_PATTERNS):
        return True

    # Check if metric name indicates network metric
    metric_lower = metric_name.lower()
    return any(keyword in metric_lower for keyword in NETWORK_METRIC_KEYWORDS)


def _is_storage_device(label: str, metric_name: str) -> bool:
    """Check if this is a storage device metric."""
    # Check if label looks like a storage device or mount point
    label_lower = label.lower()
    if any(pattern in label_lower for pattern in STORAGE_PATTERNS):
        return True

    # Check if metric name indicates storage metric
    metric_lower = metric_name.lower()
    return any(keyword in metric_lower for keyword in STORAGE_METRIC_KEYWORDS)


def _categorize_network_device(label: str, metric_name: str) -> Tuple[str, str]:
    """Categorize network device metrics."""
    device_id = label

    if "transmit" in metric_name or "tx" in metric_name:
        metric_type = "Transmit"
    elif "receive" in metric_name or "rx" in metric_name:
        metric_type = "Receive"
    else:
        metric_type = metric_name.replace('network_', '').replace('_', ' ').title()

    return device_id, metric_type


def _categorize_storage_device(label: str, metric_name: str) -> Tuple[str, str]:
    """Categorize storage device metrics."""
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


def categorize_by_device(label: str, metric_name: str) -> Tuple[str, str]:
    """
    Extract device identifier and metric type from label and metric name.

    Returns:
        Tuple of (device_id, metric_type)

    Examples:
        >>> categorize_by_device('GPU1', 'gpu_temperature')
        ('GPU1', 'Temperature')
        >>> categorize_by_device('PSU1', 'psu_input_power_watts')
        ('PSU1', 'Power Input')
        >>> categorize_by_device('eth0', 'network_receive_bytes')
        ('eth0', 'Receive')
    """
    # Try simple prefix-based rules first (GPU, PSU)
    for prefix, contains, metric_type, extractor in DEVICE_RULES:
        if label.startswith(prefix) and contains in metric_name:
            device_id = extractor(label)
            return device_id, metric_type

    # Check for network devices
    if _is_network_device(label, metric_name):
        return _categorize_network_device(label, metric_name)

    # Check for storage devices
    if _is_storage_device(label, metric_name):
        return _categorize_storage_device(label, metric_name)

    # Fallback for GPU/PSU without specific metric match
    if label.startswith('GPU'):
        return label, metric_name.replace('gpu_', '').replace('_', ' ').title()
    elif label.startswith('PSU'):
        return label, metric_name.replace('psu_', '').replace('_', ' ').title()

    # Default fallback
    return label, metric_name.replace('_', ' ').title()
