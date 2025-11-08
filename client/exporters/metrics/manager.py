"""Metrics Collector Manager - Coordinates all metrics collection"""
import logging
from typing import Any, Dict, List, Optional

from .base import MetricPoint
from .os_metrics import OSMetricsExporter
from .ipmi import IpmiExporter
from .apt import AptExporter
from .nvme import NvmeExporter
from .nvsmi import NvsmiExporter
from .bmc_fan import BMCFanExporter
from .psu import IpmicfgPsuExporter


class MetricsCollectorManager:
    """Manages metrics collection from all exporters with singleton pattern"""

    # Registry mapping config keys to exporter classes
    EXPORTER_REGISTRY = {
        "os": OSMetricsExporter,
        "ipmi": IpmiExporter,
        "apt": AptExporter,
        "nvme": NvmeExporter,
        "nvsmi": NvsmiExporter,
        "bmc_fan": BMCFanExporter,
        "ipmicfg_psu": IpmicfgPsuExporter,
    }

    def __init__(self, hw_info: Optional[Dict] = None, config: Optional[Dict] = None):
        """
        Initialize metrics exporters based on configuration.

        Args:
            hw_info: Hardware information dict (for BMC fan control)
            config: Configuration dictionary from ClientConfig
        """
        self.hw_info = hw_info or {}
        self.config = config or {}
        self.logger = logging.getLogger("dcmon.metrics_collector")

        # Get exporter enable/disable configuration
        exporter_config = self.config.get("exporters", {})

        # Get OS metrics specific configuration
        os_metrics_config = self.config.get("os_metrics", {})

        self.logger.info("Initializing metrics exporters from config...")
        self.exporters = []

        # Instantiate only enabled exporters
        for exporter_key, exporter_class in self.EXPORTER_REGISTRY.items():
            # Check if exporter is enabled (default to True if not specified)
            if not exporter_config.get(exporter_key, True):
                self.logger.debug(f"Skipping disabled exporter: {exporter_key}")
                continue

            try:
                # Special handling for exporters that need extra config
                if exporter_key == "os":
                    exporter = exporter_class(config=os_metrics_config)
                elif exporter_key == "bmc_fan":
                    exporter = exporter_class(hw_info=self.hw_info)
                else:
                    exporter = exporter_class()

                # Only add if available
                if exporter.is_available():
                    self.exporters.append(exporter)
                    self.logger.info(f"Enabled exporter: {exporter_key}")
                else:
                    self.logger.debug(f"Exporter {exporter_key} not available on this system")

            except Exception as e:
                self.logger.warning(f"Failed to initialize exporter {exporter_key}: {e}")
                continue

        self.logger.info(f"Initialized {len(self.exporters)} metrics exporters")

    async def collect_metrics(self) -> List[Dict[str, Any]]:
        """
        Collect metrics from all initialized exporters.

        Returns:
            List of metric dicts in server's expected schema format
        """
        all_metrics = []

        # Collect from each pre-initialized exporter
        for exporter in self.exporters:
            try:
                exporter_metrics = await exporter.collect()

                # Convert MetricPoint objects to dict format expected by server
                for metric in exporter_metrics:
                    # Determine value type from MetricPoint's integer classification
                    value_type = "int" if isinstance(metric.value, int) else "float"

                    metric_dict = {
                        "timestamp": metric.timestamp,
                        "metric_name": metric.name,
                        "labels": metric.labels,
                        "value_type": value_type,
                        "value": float(metric.value)  # Always send as float, server will convert if needed
                    }

                    all_metrics.append(metric_dict)

            except Exception as e:
                self.logger.warning(f"Failed to collect metrics from {exporter.__class__.__name__}: {e}")
                continue

        return all_metrics
