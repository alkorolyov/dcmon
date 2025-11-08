import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class MetricPoint:
    """Single metric data point"""
    name: str
    value: float  # Will be converted to int for appropriate metrics
    labels: Dict[str, str] = None
    timestamp: int = None

    def __post_init__(self):
        if self.labels is None:
            self.labels = {}
        if self.timestamp is None:
            self.timestamp = int(time.time())

        # Convert to int for metrics that should be integers
        if self._should_be_integer():
            self.value = int(self.value)

    def _should_be_integer(self) -> bool:
        """Check if this metric should be stored as integer"""
        integer_metrics = {
            # Memory metrics (bytes)
            'memory_total_bytes', 'memory_available_bytes', 'memory_used_bytes',

            # Network metrics (bytes/packets)
            'network_receive_bytes_total', 'network_transmit_bytes_total',
            'network_receive_packets_total', 'network_transmit_packets_total',

            # Disk metrics (bytes/operations)
            'disk_read_bytes_total', 'disk_write_bytes_total',
            'disk_reads_total', 'disk_writes_total',

            # Filesystem metrics (bytes)
            'fs_total_bytes', 'fs_free_bytes', 'fs_used_bytes',

            # GPU integer metrics
            'gpu_clock_sm', 'gpu_clock_mem', 'gpu_pcie_gen', 'gpu_pcie_width',
            'gpu_pstate', 'gpu_ecc_mode_current', 'gpu_ecc_mode_pending',
            'gpu_ecc_errors_corrected', 'gpu_ecc_errors_uncorrected',

            # APT metrics (counts)
            'apt_upgrades_pending', 'apt_reboot_required',

            # NVMe counters
            'nvme_critical_warning_total', 'nvme_media_errors_total',
            'nvme_power_cycles_total', 'nvme_power_on_hours_total',
            'nvme_data_units_written_total', 'nvme_data_units_read_total',
            'nvme_host_read_commands_total', 'nvme_host_write_commands_total',

            # PSU integer metrics (watts, celsius, rpm, status)
            'psu_input_power_watts', 'psu_output_power_watts',
            'psu_temp1_celsius', 'psu_temp2_celsius',
            'psu_fan1_rpm', 'psu_fan2_rpm', 'psu_status',
        }

        return self.name in integer_metrics


class MetricsExporter(ABC):
    """Base class for all metrics collectors"""

    def __init__(self, name: str, logger: logging.Logger = logging.getLogger(__name__)):
        self.name = name
        self.enabled = True
        self.available = self.is_available()  # Check availability once at startup
        self.last_collection = 0
        self.logger = logger

        # Log availability status
        if not self.available:
            self.logger.info(f"{self.name} metrics disabled - not available")

    def is_available(self) -> bool:
        """Check if this exporter is available. Override in subclasses for specific checks."""
        return True  # Default: always available

    @abstractmethod
    async def collect(self) -> List[MetricPoint]:
        """Collect metrics and return list of MetricPoint objects"""
        if not self.available:
            return []
        # Subclasses implement actual collection logic here

    async def safe_collect(self) -> List[MetricPoint]:
        """Safely collect metrics with error handling"""
        if not self.enabled:
            return []

        try:
            start_time = time.time()
            metrics = await self.collect()
            collection_time = time.time() - start_time

            self.logger.debug(f"{self.name}: collected {len(metrics)} metrics in {collection_time:.2f}s")
            self.last_collection = time.time()
            return metrics

        except Exception as e:
            self.logger.error(f"{self.name} collection failed: {e}")
            return []
