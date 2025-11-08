"""
Query constants and sensor mappings.

Centralized sensor mappings for different motherboard types.
"""

# Centralized sensor mappings for different motherboard types
CPU_SENSORS = [{"sensor": "CPU Temp"}, {"sensor": "TEMP_CPU"}]
VRM_SENSORS = [
    {"sensor": "CPU_VRM Temp"},
    {"sensor": "SOC_VRM Temp"},
    {"sensor": "VRMABCD Temp"},
    {"sensor": "VRMEFGH Temp"},
    {"sensor": "FSC_INDEX1"}
]
