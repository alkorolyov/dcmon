"""OS Metrics Exporter - Collects standard OS metrics: CPU, RAM, disk, network"""
import logging
import os
from typing import List, Dict, Optional

from .base import MetricsExporter, MetricPoint


class OSMetricsExporter(MetricsExporter):
    """Collects standard OS metrics: CPU, RAM, disk, network (bytes only)."""

    def __init__(self, logger: Optional[logging.Logger] = None, config: Optional[Dict] = None):
        super().__init__("os")
        self.logger = logger or logging.getLogger("os-metrics")
        self._last_cpu_stats = None  # [user, nice, system, idle]

        # Get mountpoints from config or use defaults
        self.config = config or {}
        self.mountpoints = self.config.get("mountpoints", ["/", "/var/lib/docker"])

    async def collect(self) -> List[MetricPoint]:
        metrics: List[MetricPoint] = []
        metrics.extend(await self._collect_cpu_metrics())
        metrics.extend(await self._collect_memory_metrics())
        metrics.extend(await self._collect_disk_metrics())
        metrics.extend(await self._collect_network_metrics())
        metrics.extend(await self._collect_filesystem_metrics())
        return metrics

    # ---------- CPU ----------

    async def _collect_cpu_metrics(self) -> List[MetricPoint]:
        metrics: List[MetricPoint] = []

        # Load averages
        try:
            with open("/proc/loadavg", "r") as f:
                l1, l5, l15 = f.read().split()[:3]
            metrics.extend([
                MetricPoint("cpu_load_1m", float(l1)),
                MetricPoint("cpu_load_5m", float(l5)),
                MetricPoint("cpu_load_15m", float(l15)),
            ])
        except Exception as e:
            self.logger.error(f"CPU load read error: {e}")

        # CPU usage %
        try:
            with open("/proc/stat", "r") as f:
                fields = f.readline().split()  # first line: "cpu ..."
            if fields and fields[0] == "cpu":
                user, nice, system, idle = map(int, fields[1:5])
                total = user + nice + system + idle

                if self._last_cpu_stats is not None:
                    last_user, last_nice, last_system, last_idle = self._last_cpu_stats
                    last_total = last_user + last_nice + last_system + last_idle

                    total_diff = total - last_total
                    idle_diff  = idle - last_idle

                    if total_diff > 0:
                        usage = 100.0 * (1.0 - (idle_diff / total_diff))
                        metrics.append(MetricPoint("cpu_usage_percent", usage))

                self._last_cpu_stats = [user, nice, system, idle]
        except Exception as e:
            self.logger.error(f"CPU usage read error: {e}")

        return metrics

    # ---------- Memory ----------

    async def _collect_memory_metrics(self) -> List[MetricPoint]:
        metrics: List[MetricPoint] = []

        try:
            meminfo: Dict[str, int] = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if ":" not in line:
                        continue
                    k, v = line.split(":", 1)
                    # value like "       16317852 kB"
                    num = v.strip().split()[0]
                    meminfo[k] = int(num) * 1024  # -> bytes

            total = meminfo.get("MemTotal", 0)
            available = meminfo.get("MemAvailable", 0)
            if total > 0:
                used = total - available
                usage_pct = int((used / total) * 100.0)
                metrics.extend([
                    MetricPoint("memory_total_bytes", total),
                    MetricPoint("memory_available_bytes", available),
                    MetricPoint("memory_used_bytes", used),
                    MetricPoint("memory_usage_percent", usage_pct),
                ])
        except Exception as e:
            self.logger.error(f"Meminfo read error: {e}")

        return metrics

    # ---------- Disk ------------

    async def _collect_disk_metrics(self) -> List[MetricPoint]:
        """
        Collect cumulative I/O for whole disks:
          - sdX (e.g., sda, sdb, ...)
          - nvmeXnY (e.g., nvme0n1, nvme1n1, ...)

        Emits per-device (labels: device):
          - disk_reads_total
          - disk_read_bytes_total
          - disk_writes_total
          - disk_write_bytes_total
        """
        import re
        metrics: List[MetricPoint] = []

        rx_sd = re.compile(r"^sd[a-z]+$")  # sda, sdb, ...
        rx_nvme = re.compile(r"^nvme\d+n\d+$")  # nvme0n1, nvme1n1, ...

        try:
            with open("/proc/diskstats", "r") as f:
                for line in f:
                    fields = line.split()
                    if len(fields) < 14:
                        continue

                    dev = fields[2]
                    if not (rx_sd.match(dev) or rx_nvme.match(dev)):
                        continue  # ignore partitions and other device types

                    try:
                        reads_completed = int(fields[3])  # field 4
                        sectors_read = int(fields[5])  # field 6
                        writes_completed = int(fields[7])  # field 8
                        sectors_written = int(fields[9])  # field 10
                    except ValueError:
                        continue

                    # /proc/diskstats sectors are 512-byte units
                    read_bytes = sectors_read * 512
                    write_bytes = sectors_written * 512

                    labels = {"device": dev}
                    metrics.extend([
                        # MetricPoint("disk_reads_total", reads_completed, labels),
                        MetricPoint("disk_read_bytes_total", read_bytes, labels),
                        # MetricPoint("disk_writes_total", writes_completed, labels),
                        MetricPoint("disk_write_bytes_total", write_bytes, labels),
                    ])
        except Exception as e:
            self.logger.error(f"Diskstats read error: {e}")

        return metrics

    # ---------- Network ----------

    async def _collect_network_metrics(self) -> List[MetricPoint]:
        """
        Collect network I/O from /proc/net/dev.

        Emits per-interface:
          - network_receive_bytes_total
          - network_transmit_bytes_total

        Filters:
          - skip loopback and common virtual ifaces
          - skip interfaces with zero total traffic (rx==0 and tx==0)
        """
        metrics: List[MetricPoint] = []

        skip_prefixes = ("docker", "veth", "br-", "virbr", "wlx", "tun", "tap", "tailscale")
        skip_exact = {"lo"}

        try:
            with open("/proc/net/dev", "r") as f:
                # first two lines are headers
                lines = f.readlines()[2:]

            for line in lines:
                if ":" not in line:
                    continue
                iface, payload = line.split(":", 1)
                iface = iface.strip()

                if iface in skip_exact or iface.startswith(skip_prefixes):
                    continue

                stats = payload.split()
                if len(stats) < 16:
                    continue

                try:
                    rx_bytes = int(stats[0])
                    tx_bytes = int(stats[8])
                except ValueError:
                    continue

                # Skip all-zero interfaces to reduce noise
                if rx_bytes == 0 and tx_bytes == 0:
                    continue

                labels = {"interface": iface}
                metrics.extend([
                    MetricPoint("network_receive_bytes_total", rx_bytes, labels),
                    MetricPoint("network_transmit_bytes_total", tx_bytes, labels),
                ])

        except Exception as e:
            self.logger.error(f"/proc/net/dev read error: {e}")

        return metrics

    # ---------- Filesystem ----------

    async def _collect_filesystem_metrics(self) -> List[MetricPoint]:
        """
        Collect filesystem space metrics for specific mountpoints.

        Emits per-mountpoint:
          - fs_total_bytes
          - fs_free_bytes
          - fs_used_bytes
        """
        metrics: List[MetricPoint] = []

        # Use configured mountpoints
        for mountpoint in self.mountpoints:
            try:
                # Check if mountpoint exists
                if not os.path.exists(mountpoint):
                    self.logger.debug(f"Mountpoint {mountpoint} does not exist, skipping")
                    continue

                # Get filesystem statistics
                st = os.statvfs(mountpoint)

                # Calculate sizes in bytes
                # f_frsize is the fragment size, f_blocks is total fragments
                # f_bavail is available fragments for unprivileged users
                total_bytes = st.f_frsize * st.f_blocks
                free_bytes = st.f_frsize * st.f_bavail
                used_bytes = total_bytes - free_bytes

                labels = {"mountpoint": mountpoint}
                metrics.extend([
                    MetricPoint("fs_total_bytes", total_bytes, labels),
                    MetricPoint("fs_free_bytes", free_bytes, labels),
                    MetricPoint("fs_used_bytes", used_bytes, labels),
                ])

            except Exception as e:
                self.logger.error(f"Failed to get filesystem stats for {mountpoint}: {e}")
                continue

        return metrics
