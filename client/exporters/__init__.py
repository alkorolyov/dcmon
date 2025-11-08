"""
Exporters Module - Modular metrics and log collection system

This module provides a clean separation between:
- Metrics exporters: Collect numeric time-series data
- Log exporters: Collect log entries from various sources
- Utility functions: Hardware detection and availability checks

Structure:
    exporters/
    - metrics/          # Metrics exporters
      - base.py         # MetricsExporter base class
      - os_metrics.py   # OS-level metrics (CPU, memory, disk, network)
      - ipmi.py         # IPMI sensor metrics
      - nvme.py         # NVMe drive health
      - nvsmi.py        # NVIDIA GPU metrics
      - apt.py          # Package updates
      - bmc_fan.py      # BMC fan control status
      - psu.py          # PSU monitoring
    - logs/             # Log exporters
      - base.py         # LogExporter base class
      - journal.py      # Systemd journal
      - dmesg.py        # Kernel messages
      - syslog.py       # System syslog
      - vast.py         # Vast.ai logs
    - utils.py          # Common utility functions
"""

# Import all metric exporters
from .metrics import (
    MetricPoint,
    MetricsExporter,
    OSMetricsExporter,
    ScriptExporter,
    IpmiExporter,
    AptExporter,
    NvmeExporter,
    NvsmiExporter,
    BMCFanExporter,
    IpmicfgPsuExporter,
    MetricsCollectorManager,
)

# Import all log exporters
from .logs import (
    LogEntry,
    LogExporter,
    VastLogExporter,
    SyslogExporter,
    DmesgExporter,
    JournalExporter,
    LogExporterManager,
)

# Import utility functions
from .utils import (
    is_supermicro_compatible,
    is_nvme_available,
    is_ipmi_available,
    is_ipmicfg_available,
)

__all__ = [
    # Metrics base classes
    'MetricPoint',
    'MetricsExporter',

    # Metrics exporters
    'OSMetricsExporter',
    'ScriptExporter',
    'IpmiExporter',
    'AptExporter',
    'NvmeExporter',
    'NvsmiExporter',
    'BMCFanExporter',
    'IpmicfgPsuExporter',

    # Metrics manager
    'MetricsCollectorManager',

    # Log base classes
    'LogEntry',
    'LogExporter',

    # Log exporters
    'VastLogExporter',
    'SyslogExporter',
    'DmesgExporter',
    'JournalExporter',

    # Log manager
    'LogExporterManager',

    # Utility functions
    'is_supermicro_compatible',
    'is_nvme_available',
    'is_ipmi_available',
    'is_ipmicfg_available',
]
