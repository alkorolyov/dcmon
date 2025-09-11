import asyncio
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional

try:
    from .fans import FanController, BMCFanMode
except ImportError:
    from fans import FanController, BMCFanMode


def is_supermicro_compatible(mdb_name: str) -> bool:
    """Check if motherboard supports BMC fan control based on hardware detection"""
    if not mdb_name:
        return False
    
    mdb_upper = mdb_name.upper()
    if "SUPERMICRO" not in mdb_upper:
        return False
    
    # Check for supported series (X9, X10, X11, X12, H11, H12)
    supported_series = ['X9', 'X10', 'X11', 'X12', 'H11', 'H12']
    return any(series in mdb_upper for series in supported_series)


def is_nvme_available() -> bool:
    """Check if nvme-cli is available and has device access (requires root for SMART data)"""
    import os
    import subprocess
    
    # Check if running as root (required for SMART data access)
    if os.geteuid() != 0:
        return False
    
    # Test if nvme command exists and works
    try:
        result = subprocess.run(
            ["nvme", "list", "-o", "json"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def is_ipmi_available() -> bool:
    """
    Check if IPMI is available (requires root or device access).
    Returns True if IPMI tools and devices are accessible.
    """
    import os
    import subprocess
    from pathlib import Path
    
    # Check if we have root privileges
    if os.geteuid() != 0:
        # Non-root users might still have access via device permissions
        ipmi_devices = ["/dev/ipmi0", "/dev/ipmi/0", "/dev/ipmidev/0"]
        if not any(Path(dev).exists() for dev in ipmi_devices):
            return False
    
    # Test if ipmitool command works
    try:
        result = subprocess.run(
            ["ipmitool", "mc", "info"], 
            capture_output=True, 
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def is_ipmicfg_available() -> bool:
    """
    Check if ipmicfg is available (requires root for PSU monitoring).
    Returns True if ipmicfg tools and BMC access are available.
    """
    import os
    import subprocess
    import logging
    
    logger = logging.getLogger("exporters.ipmicfg_debug")
    
    # Check if we have root privileges (required for PSU monitoring)
    if os.geteuid() != 0:
        logger.debug("ipmicfg availability: FAIL - not running as root")
        return False
    
    # Test if ipmicfg command works and PSU module is present
    try:
        result = subprocess.run(["ipmicfg", "-ver"], capture_output=True, timeout=1)
        if result.returncode != 0:
            logger.debug("ipmicfg availability: FAIL - command not available")
            return False
            
        # Check if PSU module is actually present
        psu_result = subprocess.run(["ipmicfg", "-pminfo"], capture_output=True, timeout=2)
        if psu_result.returncode != 0:
            logger.debug("ipmicfg availability: FAIL - no PSU module detected")
            return False
                
        # Check if output contains actual PSU data
        stdout_text = psu_result.stdout.decode(errors="ignore").strip()
        if "[Module 1]" not in stdout_text:
            logger.debug("ipmicfg availability: FAIL - no PSU modules in output")
            return False
                
        logger.debug("ipmicfg availability: PASS - PSU module detected")
        return True
            
    except (subprocess.TimeoutExpired, Exception) as e:
        logger.debug(f"ipmicfg availability: FAIL - {e}")
        return False
        
    except FileNotFoundError as e:
        logger.debug(f"ipmicfg availability: FAIL - {e}")
        return False
    except subprocess.TimeoutExpired as e:
        logger.debug(f"ipmicfg availability: FAIL - {e}")
        return False
    except Exception as e:
        logger.debug(f"ipmicfg availability: FAIL - {e}")
        return False


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


class OSMetricsExporter(MetricsExporter):
    """Collects standard OS metrics: CPU, RAM, disk, network (bytes only)."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        super().__init__("os")
        self.logger = logger or logging.getLogger("os-metrics")
        self._last_cpu_stats = None  # [user, nice, system, idle]

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
        
        # Mountpoints to monitor
        mountpoints = ["/", "/var/lib/docker"]
        
        for mountpoint in mountpoints:
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


class ScriptExporter(MetricsExporter):
    """Base class for script-based exporters"""

    def __init__(self, name: str, script_path: str, logger: logging.Logger):
        super().__init__(name, logger)
        self.script_path = Path(script_path)

    async def collect(self) -> List[MetricPoint]:
        """Run script and parse Prometheus format output"""
        if not self.script_path.exists():
            self.logger.warning(f"Script not found: {self.script_path}")
            return []

        try:
            # Run script with timeout
            process = await asyncio.create_subprocess_exec(
                str(self.script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)

            if process.returncode != 0:
                self.logger.error(f"{self.name} script failed: {stderr.decode()}")
                return []

            # Parse Prometheus format output
            return self._parse_prometheus_output(stdout.decode())

        except asyncio.TimeoutError:
            self.logger.error(f"{self.name} script timeout")
            return []
        except Exception as e:
            self.logger.error(f"{self.name} script error: {e}")
            return []

    def _parse_prometheus_output(self, output: str) -> List[MetricPoint]:
        """Parse Prometheus format metrics"""
        metrics = []

        for line in output.strip().split('\n'):
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue

            try:
                # Parse metric line: metric_name{labels} value
                if '{' in line:
                    # Metric with labels
                    metric_part, value_str = line.rsplit(' ', 1)
                    metric_name, labels_str = metric_part.split('{', 1)
                    labels_str = labels_str.rstrip('}')

                    # Parse labels
                    labels = {}
                    if labels_str:
                        for label_pair in labels_str.split(','):
                            if '=' in label_pair:
                                key, val = label_pair.split('=', 1)
                                labels[key.strip()] = val.strip().strip('"')
                else:
                    # Metric without labels
                    parts = line.split()
                    if len(parts) >= 2:
                        metric_name = parts[0]
                        value_str = parts[1]
                        labels = {}

                value = float(value_str)
                metrics.append(MetricPoint(metric_name, value, labels))

            except (ValueError, IndexError) as e:
                self.logger.debug(f"Failed to parse metric line: {line} - {e}")
                continue

        return metrics


class IpmiExporter(MetricsExporter):
    """
    IPMI metrics exporter (single-command parser)
    Runs exactly one command: `<ipmi_bin> sensor` and parses the table output.

    Emits per-sensor (labels: sensor):
      - ipmi_temp_celsius{sensor}
      - ipmi_fan_rpm{sensor}
      - ipmi_power_watts{sensor}
      - ipmi_voltage_volts{sensor}
      - ipmi_discrete{sensor}  (for discrete hex/bitfield rows, e.g., ChassisIntr, PROCHOT_CPU)

    Skips 'na' / 'N/A' / non-numeric readings for numeric types.
    """

    def __init__(self, ipmi_bin: str = "ipmitool"):
        self.ipmi_bin = ipmi_bin  # set to "ipmitools" if that's your binary name
        super().__init__("ipmi")
    
    def is_available(self) -> bool:
        """Check if IPMI is available (device access + privileges)"""
        return is_ipmi_available()

    async def collect(self) -> List[MetricPoint]:
        """Collect IPMI sensor metrics"""
        if not self.available:
            return []
        rows = await self._read_ipmi_sensor_table()
        metrics: List[MetricPoint] = []

        for name, reading, units, status in rows:
            sensor = name.strip()
            units_l = (units or "").strip().lower()
            reading_s = (reading or "").strip().lower()

            # Discrete sensors: value like "0x0" / "0x1" -> emit ipmi_discrete
            if units_l == "discrete":
                val = self._hex_to_int(reading_s)
                if val is not None:
                    metrics.append(MetricPoint("ipmi_discrete", int(val), {"sensor": sensor}))
                continue

            # Convert numeric readings; skip NA
            val = self._to_float(reading_s)
            if val is None:
                continue

            # Normalize units and emit typed metrics
            if units_l in ("degrees c", "celsius", "degc", "c"):
                metrics.append(MetricPoint("ipmi_temp_celsius", int(val), {"sensor": sensor}))
            elif units_l == "rpm":
                metrics.append(MetricPoint("ipmi_fan_rpm", int(val), {"sensor": sensor}))
            elif units_l in ("watts", "w"):
                metrics.append(MetricPoint("ipmi_power_watts", int(val), {"sensor": sensor}))
            elif units_l in ("volts", "v"):
                metrics.append(MetricPoint("ipmi_voltage_volts", float(val), {"sensor": sensor}))
            # (optional) add amps if you want:
            # elif units_l in ("amps", "a"):
            #     metrics.append(MetricPoint("ipmi_current_amps", float(val), {"sensor": sensor}))

        return metrics

    # ----- helpers -----

    async def _read_ipmi_sensor_table(self) -> List[List[str]]:
        """
        Parse the standard table from: `<ipmi_bin> sensor`
        Each data row looks like: NAME | READING | UNITS | STATUS | ...
        Returns rows of [name, reading, units, status]
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self.ipmi_bin, "sensor",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return []

        out, err = await proc.communicate()
        if proc.returncode != 0:
            return []

        rows: List[List[str]] = []
        for ln in out.decode(errors="ignore").splitlines():
            if "|" not in ln:
                continue
            cols = [c.strip() for c in ln.split("|")]
            if len(cols) < 4:
                continue
            name, reading, units, status = cols[0], cols[1], cols[2], cols[3]
            rows.append([name, reading, units, status])
        return rows

    def _to_float(self, s: str) -> Optional[float]:
        if not s or s in ("na", "n/a", "no reading", "disabled"):
            return None
        if s.startswith("0x"):  # discrete hex → not a numeric reading
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _hex_to_int(self, s: str) -> Optional[int]:
        if not s or not s.startswith("0x"):
            return None
        try:
            return int(s, 16)
        except ValueError:
            return None


class AptExporter(MetricsExporter):
    """APT updates exporter (Python-only)
    Emits:
      - apt_upgrades_pending_total (count of upgradable packages)
      - apt_reboot_required (0/1 based on /var/run/reboot-required)
    """
    def __init__(self):
        super().__init__("apt", logging.getLogger())

    async def collect(self) -> List[MetricPoint]:
        import asyncio
        from pathlib import Path

        # Count upgradable packages without shell pipelines
        proc = await asyncio.create_subprocess_exec(
            "apt", "list", "--upgradable",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            # If apt is not available or returns error, emit nothing
            return []

        # Filter out the "Listing..." header and empty lines
        lines = [ln.strip() for ln in out.decode().splitlines() if ln.strip()]
        upgradable_count = sum(1 for ln in lines if not ln.startswith("Listing..."))

        reboot_required = 1 if Path("/var/run/reboot-required").exists() else 0

        return [
            MetricPoint("apt_upgrades_pending", int(upgradable_count), {}),
            MetricPoint("apt_reboot_required", int(reboot_required), {}),
        ]

# class AptExporter(ScriptExporter):
#     """APT updates exporter"""
# 
#     def __init__(self):
#         super().__init__("apt", "/home/ergot/projects/dcmon/client/exporters/apt.sh", logging.getLogger(__name__))


class NvmeExporter(MetricsExporter):
    """
    NVMe metrics exporter (Python-only, replaces nvme.sh)

    Emits per NVMe controller (labels: device, model):
      - nvme_temperature_celsius
      - nvme_available_spare_percent
      - nvme_available_spare_threshold_percent
      - nvme_percentage_used
      - nvme_data_units_read_total
      - nvme_data_units_read_bytes_total
      - nvme_data_units_written_total
      - nvme_data_units_written_bytes_total
      - nvme_power_cycles_total
      - nvme_power_on_hours_total
      - nvme_unsafe_shutdowns_total
      - nvme_media_errors_total
      - nvme_error_log_entries_total
      - nvme_critical_warning
    """

    # NVMe SMART “data units” are 512,000 bytes each (per NVMe spec / nvme-cli)
    DATA_UNIT_BYTES = 512_000

    def __init__(self):
        super().__init__("nvme")
    
    def is_available(self) -> bool:
        """Check if nvme-cli is available (requires root for SMART data access)"""
        return is_nvme_available()

    async def collect(self) -> List[MetricPoint]:
        if not self.available:
            return []
            
        devices = await self._list_nvme_devices()
        if not devices:
            return []
        metrics: List[MetricPoint] = []
        for dev_path, model in devices:
            try:
                smart = await self._smart_log(dev_path)
            except Exception:
                continue

            labels = {"device": dev_path, "model": model or "unknown"}

            # Helpers (default to 0 if missing)
            def g(key: str, default=0):
                val = smart.get(key, default)
                try:
                    return int(val)
                except Exception:
                    try:
                        return float(val)
                    except Exception:
                        return default

            # Core SMART values
            temperature_c      = g("temperature")                     # °C
            avail_spare        = g("available_spare")                 # %
            avail_spare_thr    = g("available_spare_threshold")       # %
            percent_used       = g("percentage_used")                 # %
            data_units_read    = g("data_units_read")                 # count
            data_units_written = g("data_units_written")              # count
            power_cycles       = g("power_cycles")
            power_on_hours     = g("power_on_hours")
            unsafe_shutdowns   = g("unsafe_shutdowns")
            media_errors       = g("media_errors")
            error_log_entries  = g("num_err_log_entries")
            critical_warning   = g("critical_warning")

            metrics.extend([
                MetricPoint("nvme_temperature_celsius", int(temperature_c) - 273, labels),
                MetricPoint("nvme_available_spare_percent", int(avail_spare), labels),
                MetricPoint("nvme_available_spare_threshold_percent", int(avail_spare_thr), labels),
                MetricPoint("nvme_percentage_used", int(percent_used), labels),

                MetricPoint("nvme_data_units_read_total", int(data_units_read), labels),
                MetricPoint("nvme_data_units_read_bytes_total", int(data_units_read) * self.DATA_UNIT_BYTES, labels),
                # MetricPoint("nvme_data_units_written_total", float(data_units_written), labels),
                # MetricPoint("nvme_data_units_written_bytes_total", float(data_units_written) * self.DATA_UNIT_BYTES, labels),

                # MetricPoint("nvme_power_cycles_total", int(power_cycles), labels),
                MetricPoint("nvme_power_on_hours_total", int(power_on_hours), labels),
                MetricPoint("nvme_unsafe_shutdowns_total", int(unsafe_shutdowns), labels),
                MetricPoint("nvme_media_errors_total", int(media_errors), labels),
                MetricPoint("nvme_error_log_entries_total", int(error_log_entries), labels),
                MetricPoint("nvme_critical_warning", int(critical_warning), labels),
            ])

        return metrics

    # ---------- helpers ----------

    async def _list_nvme_devices(self) -> List[tuple]:
        """
        Returns a list of (device_path, model) for NVMe controllers,
        e.g. [('/dev/nvme0', 'SAMSUNG MZVL...'), ('/dev/nvme1', '...')]
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvme", "list", "-o", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
            if proc.returncode != 0:
                return []

            data = json.loads(out.decode() or "{}")
            devs = []
            # nvme-cli json usually has "Devices": [{ "DevicePath": "/dev/nvme0", "ModelNumber": "...", ...}, ...]
            for d in data.get("Devices", []):
                path = d.get("DevicePath")
                model = d.get("ModelNumber") or d.get("Model") or d.get("ModelNumber ")  # be tolerant
                if path and path.startswith("/dev/nvme"):
                    devs.append((path, model))
            return devs
        except Exception:
            return []

    async def _smart_log(self, device_path: str) -> Dict:
        """
        Fetch SMART log as a dict for the given NVMe device (controller).
        """
        proc = await asyncio.create_subprocess_exec(
            "nvme", "smart-log", device_path, "-o", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"nvme smart-log failed for {device_path}: {err.decode().strip()}")
        try:
            return json.loads(out.decode() or "{}")
        except Exception as e:
            raise RuntimeError(f"bad JSON from nvme smart-log {device_path}: {e}")


class NvsmiExporter(MetricsExporter):
    """
    Optimized NVIDIA GPU collector:
    - Only emits essential metrics: temp, power_draw, util_{gpu,mem}, fan, clocks_{sm,mem},
      pcie_{gen,width}, memory_usage (%)
    - Removed: power_limit, pstate, ecc_mode (not essential for monitoring)
    - Labels: model, bus_id
    """
    def __init__(self):
        super().__init__("nvslim")

    async def collect(self) -> List[MetricPoint]:
        # Ask nvidia-smi just for essential fields (no units to simplify parsing)
        fields = [
            "gpu_bus_id",
            "pcie.link.gen.current",
            "pcie.link.width.current",
            "fan.speed",
            "utilization.gpu",
            "utilization.memory",
            "temperature.gpu",
            "power.draw",
            "power.limit",
            "clocks.sm",
            "clocks.mem",
            "memory.total",
            "memory.reserved",
            "memory.used",
            "name",
        ]
        cmd = [
            "nvidia-smi",
            f"--query-gpu={','.join(fields)}",
            "--format=csv,noheader,nounits"
        ]

        # Run once; supports multi-GPU (one CSV line per GPU)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"nvidia-smi failed: {err.decode().strip()}")

        metrics: List[MetricPoint] = []
        for line in out.decode().strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            (bus_id, pcie_gen, pcie_width, fan, util_gpu, util_mem,
             temp, pwr_draw, pwr_limit, clk_sm, clk_mem,
             mem_total, mem_reserved, mem_used, name) = parts

            # Tidy labels (match your bash exporter semantics)
            # bus_id like "00000000:01:00.0" -> "01:00.0"
            bus_id_short = ":".join(bus_id.split(":")[-2:])
            model = " ".join(name.split()[-2:])  # keep the short "RTX 5090" style

            labels = {"model": model, "bus_id": bus_id_short}

            # Parse numerics
            pcie_gen = int(pcie_gen); pcie_width = int(pcie_width)
            fan = int(fan); util_gpu = float(util_gpu); util_mem = float(util_mem)
            temp = int(temp); pwr_draw = int(float(pwr_draw)); pwr_limit = int(float(pwr_limit))
            clk_sm = int(float(clk_sm)); clk_mem = int(float(clk_mem))
            mem_total = float(mem_total); mem_reserved = float(mem_reserved); mem_used = float(mem_used)

            mem_usage_pct = int((mem_reserved + mem_used) / mem_total * 100.0) if mem_total > 0 else 0.0

            # Emit only essential metrics (optimized for monitoring)
            metrics.extend([
                MetricPoint("gpu_temperature", temp, labels),
                MetricPoint("gpu_power_draw", pwr_draw, labels),
                MetricPoint("gpu_power_limit", pwr_limit, labels),
                MetricPoint("gpu_utilization_gpu", util_gpu, labels),
                MetricPoint("gpu_utilization_memory", util_mem, labels),
                MetricPoint("gpu_fan_speed", fan, labels),
                MetricPoint("gpu_clock_sm", clk_sm, labels),
                MetricPoint("gpu_clock_mem", clk_mem, labels),
                MetricPoint("gpu_pcie_gen", pcie_gen, labels),
                MetricPoint("gpu_pcie_width", pcie_width, labels),
                MetricPoint("gpu_memory_usage", round(mem_usage_pct, 2), labels),
            ])

        return metrics


class BMCFanExporter(MetricsExporter):
    """Exports BMC fan control metrics via IPMI"""
    
    def __init__(self, hw_info: Dict = None):
        self.hw_info = hw_info or {}
        self.fan_ctrl = FanController()  # Create once and reuse
        super().__init__("bmc_fan")
    
    def is_available(self) -> bool:
        """Check if BMC fan control is available (Supermicro hardware + IPMI access)"""
        mdb_name = self.hw_info.get("mdb_name", "")
        return is_supermicro_compatible(mdb_name) and is_ipmi_available()
    
    async def collect(self) -> List[MetricPoint]:
        """Collect BMC fan metrics"""
        if not self.available:
            return []
            
        metrics = []
        
        try:
            # Use cached fan controller instance
            status = await self.fan_ctrl.get_fan_status()
            
            # BMC Fan Mode metric
            if status.get('bmc_mode_value') is not None:
                metrics.append(MetricPoint(
                    "bmc_fan_mode", 
                    status['bmc_mode_value']
                ))
            
            # Fan zone speed metrics
            zone_0_speed = status.get('zone_0_speed')
            if zone_0_speed is not None:
                metrics.append(MetricPoint(
                    "bmc_fan_zone_speed",
                    zone_0_speed,
                    {"zone": "0"}
                ))
            
            zone_1_speed = status.get('zone_1_speed') 
            if zone_1_speed is not None:
                metrics.append(MetricPoint(
                    "bmc_fan_zone_speed", 
                    zone_1_speed,
                    {"zone": "1"}
                ))
                
        except Exception as e:
            # Don't break metrics collection if IPMI fails
            self.logger.debug(f"BMC fan metrics unavailable: {e}")
            
        return metrics


class IpmicfgPsuExporter(MetricsExporter):
    """
    ipmicfg PSU metrics exporter for Supermicro systems.
    Collects power supply metrics using the ipmicfg tool.
    
    Emits per-PSU (labels: module):
      - psu_input_power_watts
      - psu_output_power_watts
      - psu_temp1_celsius
      - psu_temp2_celsius
      - psu_fan1_rpm
      - psu_fan2_rpm
      - psu_status (string: "OK", "Warning", etc.)
    """
    
    def __init__(self):
        super().__init__("ipmicfg_psu")
    
    def is_available(self) -> bool:
        """Check if ipmicfg is available for PSU monitoring"""
        return is_ipmicfg_available()
    
    async def collect(self) -> List[MetricPoint]:
        """Collect PSU metrics using ipmicfg"""
        if not self.available:
            return []
        
        try:
            # Run ipmicfg -pminfo to get PSU information
            proc = await asyncio.create_subprocess_exec(
                "ipmicfg", "-pminfo",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            
            if proc.returncode != 0:
                self.logger.error(f"ipmicfg -pminfo failed: {stderr.decode()}")
                return []
            
            return self._parse_psu_output(stdout.decode())
            
        except asyncio.TimeoutError:
            self.logger.error("ipmicfg -pminfo command timeout")
            return []
        except Exception as e:
            self.logger.error(f"ipmicfg PSU collection error: {e}")
            return []
    
    def _parse_psu_output(self, output: str) -> List[MetricPoint]:
        """Parse ipmicfg -pminfo output into metrics"""
        metrics = []
        current_psu = None
        current_data = {}
        
        for line in output.splitlines():
            line = line.strip()
            
            # Skip empty lines and headers
            if not line or line.startswith('Item') or line.startswith('----'):
                continue
            
            # Detect PSU section headers (e.g., "[SlaveAddress = 78h] [Module 1]")
            if '[Module' in line and ']' in line:
                # Save previous PSU data if exists
                if current_psu and current_data:
                    metrics.extend(self._create_psu_metrics(current_psu, current_data))
                
                # Extract module number and convert to PSU format
                # "[SlaveAddress = 78h] [Module 1]" -> "PSU1"
                import re
                match = re.search(r'\[Module (\d+)\]', line)
                if match:
                    module_num = match.group(1)
                    current_psu = f"PSU{module_num}"
                    current_data = {}
                continue
            
            # Parse key-value pairs
            if '|' in line:
                parts = line.split('|', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    current_data[key] = value
        
        # Don't forget the last PSU
        if current_psu and current_data:
            metrics.extend(self._create_psu_metrics(current_psu, current_data))
        
        return metrics
    
    def _create_psu_metrics(self, psu_module: str, data: Dict[str, str]) -> List[MetricPoint]:
        """Convert PSU data dictionary to MetricPoint objects"""
        metrics = []
        labels = {"module": psu_module}
        
        # Helper to safely extract numeric values
        def get_numeric(key: str, default: int = 0) -> int:
            value = data.get(key, "").strip()
            try:
                # Extract numeric part (remove units like "W", "RPM", "C", etc.)
                numeric_str = ''.join(c for c in value if c.isdigit() or c == '.')
                return int(float(numeric_str)) if numeric_str else default
            except (ValueError, TypeError):
                return default
        
        # Helper to extract temperature (handle "25C/77F" format)
        def get_temperature(key: str, default: int = 0) -> int:
            value = data.get(key, "").strip()
            try:
                # Extract Celsius part from "25C/77F" format
                if 'C/' in value:
                    celsius_str = value.split('C/')[0]
                    return int(celsius_str)
                else:
                    return get_numeric(key, default)
            except (ValueError, TypeError):
                return default
        
        # Extract power metrics (watts)
        input_power = get_numeric("Input Power")
        if input_power > 0:
            metrics.append(MetricPoint("psu_input_power_watts", input_power, labels))
        
        # Note: Field name is "Main Output Power" in pminfo output
        output_power = get_numeric("Main Output Power") 
        if output_power > 0:
            metrics.append(MetricPoint("psu_output_power_watts", output_power, labels))
        
        # Extract temperature metrics (celsius) - handle "25C/77F" format
        temp1 = get_temperature("Temperature 1")
        if temp1 > 0:
            metrics.append(MetricPoint("psu_temp1_celsius", temp1, labels))
            
        temp2 = get_temperature("Temperature 2")
        if temp2 > 0:
            metrics.append(MetricPoint("psu_temp2_celsius", temp2, labels))
        
        # Extract fan metrics (RPM) - note field names are "Fan 1", "Fan 2" in pminfo
        fan1_rpm = get_numeric("Fan 1")
        if fan1_rpm > 0:
            metrics.append(MetricPoint("psu_fan1_rpm", fan1_rpm, labels))
            
        fan2_rpm = get_numeric("Fan 2") 
        if fan2_rpm > 0:
            metrics.append(MetricPoint("psu_fan2_rpm", fan2_rpm, labels))
        
        # Extract status (string) - for now, map to numeric for storage compatibility
        status = data.get("Status", "").strip()
        if status:
            # Map status strings to numeric values for database storage
            status_map = {"OK": 0, "Warning": 1, "Critical": 2, "Unknown": 3}
            status_value = status_map.get(status, 3)  # Default to Unknown
            metrics.append(MetricPoint("psu_status", status_value, {**labels, "status": status}))
        
        return metrics


@dataclass
class LogEntry:
    """Represents a collected log entry"""
    log_source: str  # 'dmesg', 'journal', 'syslog'
    log_timestamp: int
    content: str
    severity: Optional[str] = None


class LogExporter:
    """
    Incremental log collection for troubleshooting.
    Tracks cursor positions and collects only new log entries.
    """
    
    def __init__(self, auth_dir: Path, config: Optional[Dict] = None):
        self.auth_dir = Path(auth_dir)
        self.cursors_file = self.auth_dir / "log-cursors.json"
        self.config = config or {}
        self.logger = logging.getLogger("dcmon.log_exporter")
        
        # Load cursors on initialization
        self.cursors = self._load_cursors()
        
        # Configuration
        log_config = self.config.get('log_monitoring', {})
        self.enabled = log_config.get('enabled', False)
        self.max_lines_per_cycle = log_config.get('max_lines_per_cycle', 50)
        self.severity_filter = log_config.get('severity_filter', 'WARN')
        self.enabled_sources = log_config.get('sources', ['dmesg', 'journal'])
        
        # Cache boot time once - only changes on system reboot (which restarts client)
        self.boot_time = self._get_boot_time() if self.enabled and 'dmesg' in self.enabled_sources else None
        
        # Check vast log availability
        self.vast_log_available = Path('/var/lib/vastai_kaalia/kaalia.log').exists()
        if self.enabled and 'vast' in self.enabled_sources and not self.vast_log_available:
            self.logger.info("vast logs disabled - /var/lib/vastai_kaalia/kaalia.log not available")
    
    def _load_cursors(self) -> Dict:
        """Load cursor positions from persistent storage."""
        try:
            if self.cursors_file.exists():
                with open(self.cursors_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading cursors: {e}")
        
        # Default cursors
        return {
            "dmesg": {"last_line": 0, "last_timestamp": 0},
            "journal": {"cursor": "", "last_timestamp": 0},
            "syslog": {"byte_offset": 0, "inode": 0, "last_timestamp": 0},
            "vast": {"byte_offset": 0, "inode": 0, "last_timestamp": 0}
        }
    
    def _save_cursors(self) -> None:
        """Save cursor positions to persistent storage."""
        try:
            self.auth_dir.mkdir(parents=True, exist_ok=True)
            with open(self.cursors_file, 'w') as f:
                json.dump(self.cursors, f)
        except Exception as e:
            raise Exception(f"Failed to save cursor positions: {e}")
    
    def _parse_severity(self, line: str) -> str:
        """Extract severity level from log line."""
        line_upper = line.upper()
        if any(word in line_upper for word in ['ERROR', 'ERR', 'FATAL', 'FAIL', 'CRITICAL']):
            return 'ERROR'
        elif any(word in line_upper for word in ['WARN', 'WARNING']):
            return 'WARN'
        elif any(word in line_upper for word in ['DEBUG']):
            return 'DEBUG'
        else:
            return 'INFO'  # Default all unrecognized to INFO
    
    def _should_include_severity(self, severity: str) -> bool:
        """Check if log entry should be included based on severity filter."""
        severity_levels = ['DEBUG', 'INFO', 'WARN', 'ERROR']
        try:
            min_level_idx = severity_levels.index(self.severity_filter)
            current_level_idx = severity_levels.index(severity)
            return current_level_idx >= min_level_idx
        except ValueError:
            return True  # Include if severity not recognized
    
    def _get_boot_time(self) -> int:
        """Get system boot time from /proc/stat."""
        try:
            with open('/proc/stat', 'r') as f:
                for line in f:
                    if line.startswith('btime'):
                        return int(line.split()[1])
            raise Exception("btime not found in /proc/stat")
        except Exception as e:
            raise Exception(f"Failed to get boot time: {e}")
    
    def _parse_dmesg_timestamp(self, line: str) -> Optional[int]:
        """Parse dmesg timestamp from kernel line format [12345.67]."""
        import re
        try:
            # Match dmesg timestamp format: [12345.67]
            match = re.match(r'^\[(\d+\.\d+)\]', line.strip())
            if not match:
                return None
            
            kernel_seconds = float(match.group(1))
            # Use cached boot time - no file I/O needed
            return self.boot_time + int(kernel_seconds)
        except Exception as e:
            raise Exception(f"Failed to parse dmesg timestamp from '{line[:50]}...': {e}")
    
    def _parse_syslog_timestamp(self, line: str) -> Optional[int]:
        """Parse syslog timestamp from standard format 'Sep  7 13:14:25' and convert to UTC."""
        import re
        from datetime import datetime, timezone
        try:
            # Match syslog timestamp format: Sep  7 13:14:25 hostname
            match = re.match(r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})', line.strip())
            if not match:
                return None
            
            timestamp_str = match.group(1)
            # Add current year since syslog doesn't include it
            current_year = datetime.now().year
            full_timestamp = f"{current_year} {timestamp_str}"
            
            # Parse to datetime in local timezone, then convert to UTC
            dt_local = datetime.strptime(full_timestamp, "%Y %b %d %H:%M:%S")
            # Assume syslog timestamp is in system's local timezone
            dt_local = dt_local.replace(tzinfo=datetime.now().astimezone().tzinfo)
            # Convert to UTC unix timestamp
            return int(dt_local.astimezone(timezone.utc).timestamp())
        except Exception as e:
            raise Exception(f"Failed to parse syslog timestamp from '{line[:50]}...': {e}")
    
    def _parse_vast_timestamp(self, line: str) -> Optional[int]:
        """Parse vast timestamp from format '[2025-09-07 15:33:07.798]' and convert to UTC."""
        import re
        from datetime import datetime, timezone
        try:
            # Match vast timestamp format: [YYYY-MM-DD HH:MM:SS.mmm]
            match = re.match(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]', line.strip())
            if not match:
                return None
            
            timestamp_str = match.group(1)
            # Parse to datetime in local timezone (vast logs appear to be in local time)
            dt_local = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
            # Assume vast timestamp is in system's local timezone
            dt_local = dt_local.replace(tzinfo=datetime.now().astimezone().tzinfo)
            # Convert to UTC unix timestamp
            return int(dt_local.astimezone(timezone.utc).timestamp())
        except Exception as e:
            raise Exception(f"Failed to parse vast timestamp from '{line[:50]}...': {e}")
    
    def _strip_syslog_timestamp(self, line: str) -> str:
        """Strip timestamp from syslog line, keeping only message content."""
        import re
        # Match and remove syslog timestamp format: Sep  7 13:14:25 hostname
        match = re.match(r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(.*)', line.strip())
        if match:
            return match.group(3)  # Return only the message part
        return line.strip()  # Return original if no match
    
    def _strip_vast_metadata(self, line: str) -> str:
        """Strip timestamp and metadata from vast line, keeping only message content."""
        import re
        # Match and remove vast format: [2025-09-07 15:33:07.798] [Kaalia] [info] P2033  message
        match = re.match(r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] \[Kaalia\] \[(?:info|warn|error)\] P\d+\s+(.*)', line.strip())
        if match:
            return match.group(1)  # Return only the message part
        return line.strip()  # Return original if no match
    
    def _is_first_run(self) -> bool:
        """Check if this is the first run (no cursor file or empty cursors)."""
        if not self.cursors_file.exists():
            return True
        
        # Check if cursors are at default/empty state
        default_cursors = {
            "dmesg": {"last_line": 0, "last_timestamp": 0},
            "journal": {"cursor": "", "last_timestamp": 0},
            "syslog": {"byte_offset": 0, "inode": 0, "last_timestamp": 0},
            "vast": {"byte_offset": 0, "inode": 0, "last_timestamp": 0}
        }
        return self.cursors == default_cursors

    def collect_new_logs(self) -> List[LogEntry]:
        """Collect new log entries from all enabled sources."""
        if not self.enabled:
            return []
        
        is_first_run = self._is_first_run()
        if is_first_run:
            self.logger.info("First run detected - collecting extended log history")
            
        all_logs = []
        
        if 'dmesg' in self.enabled_sources:
            if is_first_run:
                all_logs.extend(self._collect_dmesg_history())
            else:
                all_logs.extend(self._collect_dmesg_incremental())
                
        if 'journal' in self.enabled_sources:
            if is_first_run:
                all_logs.extend(self._collect_journal_history())
            else:
                all_logs.extend(self._collect_journal_incremental())
                
        if 'syslog' in self.enabled_sources:
            if is_first_run:
                all_logs.extend(self._collect_syslog_history())
            else:
                all_logs.extend(self._collect_syslog_incremental())
        
        if 'vast' in self.enabled_sources and self.vast_log_available:
            if is_first_run:
                all_logs.extend(self._collect_vast_history())
            else:
                all_logs.extend(self._collect_vast_incremental())
        
        # Apply size limit (different for first run vs normal)
        max_entries = 3000 if is_first_run else self.max_lines_per_cycle
        if len(all_logs) > max_entries:
            # Keep most recent entries
            all_logs = sorted(all_logs, key=lambda x: x.log_timestamp)[-max_entries:]
            self.logger.warning(f"Log collection truncated to {max_entries} entries")
        
        # Save updated cursors
        if all_logs:
            self._save_cursors()
            
        return all_logs
    
    def _collect_dmesg_incremental(self) -> List[LogEntry]:
        """Collect new dmesg entries using line counting."""
        try:
            import subprocess
            
            # Get current dmesg output
            result = subprocess.run(['dmesg'], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return []
            
            lines = result.stdout.strip().split('\n')
            cursor = self.cursors['dmesg']
            last_line = cursor['last_line']
            
            # Get new lines
            if len(lines) <= last_line:
                return []  # No new lines
                
            new_lines = lines[last_line:]
            entries = []
            
            for i, line in enumerate(new_lines):
                if not line.strip():
                    continue
                    
                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue
                
                # Parse actual dmesg timestamp
                parsed_timestamp = self._parse_dmesg_timestamp(line)
                if parsed_timestamp is None:
                    # No timestamp found - skip this entry (fail-fast)
                    continue
                    
                entries.append(LogEntry(
                    log_source='dmesg',
                    log_timestamp=parsed_timestamp,
                    content=line.strip(),
                    severity=severity
                ))
            
            # Update cursor
            self.cursors['dmesg']['last_line'] = len(lines)
            self.cursors['dmesg']['last_timestamp'] = int(time.time())
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect dmesg incremental: {e}")
    
    def _collect_journal_incremental(self) -> List[LogEntry]:
        """Collect new journal entries using systemd cursor."""
        try:
            import subprocess
            
            cursor = self.cursors['journal']
            cmd = ['journalctl', '--output=json', '--no-pager']
            
            # Use cursor if available
            if cursor['cursor']:
                cmd.extend(['--cursor', cursor['cursor']])
            else:
                # First run - get last hour
                cmd.extend(['--since', '1 hour ago'])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return []
            
            entries = []
            last_cursor = cursor['cursor']
            
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                    
                try:
                    entry = json.loads(line)
                    message = entry.get('MESSAGE', '')
                    if not message:
                        continue
                    
                    # Extract timestamp
                    timestamp_usec = int(entry.get('__REALTIME_TIMESTAMP', 0))
                    timestamp = timestamp_usec // 1000000  # Convert to seconds
                    
                    # Extract severity
                    priority = entry.get('PRIORITY', '6')  # Default to INFO
                    severity_map = {'0': 'ERROR', '1': 'ERROR', '2': 'ERROR', '3': 'ERROR',
                                   '4': 'WARN', '5': 'INFO', '6': 'INFO', '7': 'DEBUG'}
                    severity = severity_map.get(str(priority), 'INFO')
                    
                    if not self._should_include_severity(severity):
                        continue
                    
                    # Format content with context (no fallbacks - fail fast)
                    unit = entry.get('_SYSTEMD_UNIT', '')
                    identifier = entry.get('SYSLOG_IDENTIFIER', '')
                    pid = entry.get('_PID', '')
                    
                    # Build context prefix
                    context_parts = []
                    if unit:
                        context_parts.append(unit)
                    if identifier and pid:
                        context_parts.append(f"{identifier}[{pid}]")
                    elif identifier:
                        context_parts.append(identifier)
                    
                    if context_parts:
                        formatted_content = f"[{'] ['.join(context_parts)}]: {message.strip()}"
                    else:
                        formatted_content = message.strip()
                    
                    entries.append(LogEntry(
                        log_source='journal',
                        log_timestamp=timestamp,
                        content=formatted_content,
                        severity=severity
                    ))
                    
                    # Update cursor from this entry
                    last_cursor = entry.get('__CURSOR', last_cursor)
                    
                except json.JSONDecodeError:
                    continue
            
            # Update cursor
            if entries:
                self.cursors['journal']['cursor'] = last_cursor
                self.cursors['journal']['last_timestamp'] = int(time.time())
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect journal incremental: {e}")
    
    def _collect_syslog_incremental(self) -> List[LogEntry]:
        """Collect new syslog entries using file position tracking."""
        try:
            syslog_file = Path('/var/log/syslog')
            if not syslog_file.exists():
                return []
            
            cursor = self.cursors['syslog']
            stat = syslog_file.stat()
            
            # Check for log rotation (inode changed)
            if cursor['inode'] != 0 and cursor['inode'] != stat.st_ino:
                # Log was rotated, start from beginning
                cursor['byte_offset'] = 0
                cursor['inode'] = stat.st_ino
            
            # Read new content
            with open(syslog_file, 'r') as f:
                f.seek(cursor['byte_offset'])
                new_content = f.read()
                new_offset = f.tell()
            
            if not new_content.strip():
                return []
            
            entries = []
            
            for line in new_content.strip().split('\n'):
                if not line.strip():
                    continue
                    
                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue
                
                # Parse actual syslog timestamp
                parsed_timestamp = self._parse_syslog_timestamp(line)
                if parsed_timestamp is None:
                    # No timestamp found - skip this entry (fail-fast)
                    continue
                    
                entries.append(LogEntry(
                    log_source='syslog',
                    log_timestamp=parsed_timestamp,
                    content=self._strip_syslog_timestamp(line),
                    severity=severity
                ))
            
            # Update cursor
            self.cursors['syslog']['byte_offset'] = new_offset
            self.cursors['syslog']['inode'] = stat.st_ino
            self.cursors['syslog']['last_timestamp'] = int(time.time())
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect syslog incremental: {e}")

    def _collect_vast_incremental(self) -> List[LogEntry]:
        """Collect new vast log entries using file position tracking."""
        try:
            vast_file = Path('/var/lib/vastai_kaalia/kaalia.log')
            if not vast_file.exists():
                return []
            
            # Handle missing cursor (first run for this log source)
            if 'vast' not in self.cursors:
                return self._collect_vast_history()
            
            cursor = self.cursors['vast']
            stat = vast_file.stat()
            
            # Check for log rotation (inode changed) - simplified, no rotation handling
            if cursor['inode'] != 0 and cursor['inode'] != stat.st_ino:
                # File was replaced, start from beginning  
                cursor['byte_offset'] = 0
                cursor['inode'] = stat.st_ino
            
            # Read new content
            with open(vast_file, 'r') as f:
                f.seek(cursor['byte_offset'])
                new_content = f.read()
                new_offset = f.tell()
            
            if not new_content.strip():
                return []
            
            entries = []
            
            for line in new_content.strip().split('\n'):
                if not line.strip():
                    continue
                    
                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue
                
                # Parse actual vast timestamp
                parsed_timestamp = self._parse_vast_timestamp(line)
                if parsed_timestamp is None:
                    # No timestamp found - skip this entry (fail-fast)
                    continue
                    
                entries.append(LogEntry(
                    log_source='vast',
                    log_timestamp=parsed_timestamp,
                    content=self._strip_vast_metadata(line),
                    severity=severity
                ))
            
            # Update cursor
            self.cursors['vast']['byte_offset'] = new_offset
            self.cursors['vast']['inode'] = stat.st_ino
            self.cursors['vast']['last_timestamp'] = int(time.time())
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect vast incremental: {e}")

    def _collect_dmesg_history(self) -> List[LogEntry]:
        """Collect full dmesg history since boot (first run)."""
        try:
            import subprocess
            
            # Get all dmesg output since boot
            result = subprocess.run(['dmesg'], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise Exception(f"dmesg command failed: {result.stderr}")
            
            lines = result.stdout.strip().split('\n')
            entries = []
            
            # Crop to last 1000 lines if exceeding
            if len(lines) > 1000:
                lines = lines[-1000:]
                self.logger.info(f"dmesg history cropped to last 1000 lines")
            
            for line in lines:
                if not line.strip():
                    continue
                    
                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue
                
                # Parse actual dmesg timestamp
                parsed_timestamp = self._parse_dmesg_timestamp(line)
                if parsed_timestamp is None:
                    # No timestamp found - skip this entry (fail-fast)
                    continue
                    
                entries.append(LogEntry(
                    log_source='dmesg',
                    log_timestamp=parsed_timestamp,
                    content=line.strip(),
                    severity=severity
                ))
            
            # Set cursor to total line count for future incremental collection
            self.cursors['dmesg']['last_line'] = len(result.stdout.strip().split('\n'))
            self.cursors['dmesg']['last_timestamp'] = int(time.time())
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect dmesg history: {e}")

    def _collect_journal_history(self) -> List[LogEntry]:
        """Collect journal history for last 24 hours OR since boot (first run)."""
        try:
            import subprocess
            
            # Get last 24 hours of journal entries
            cmd = ['journalctl', '--output=json', '--no-pager', '--since', '24 hours ago']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                raise Exception(f"journalctl command failed: {result.stderr}")
            
            entries = []
            last_cursor = ""
            entry_count = 0
            
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                    
                try:
                    entry = json.loads(line)
                    message = entry.get('MESSAGE', '')
                    if not message:
                        continue
                    
                    # Crop to 1000 entries max
                    entry_count += 1
                    if entry_count > 1000:
                        self.logger.info(f"journal history cropped to 1000 entries")
                        break
                    
                    # Extract timestamp
                    timestamp_usec = int(entry.get('__REALTIME_TIMESTAMP', 0))
                    timestamp = timestamp_usec // 1000000
                    
                    # Extract severity
                    priority = entry.get('PRIORITY', '6')
                    severity_map = {'0': 'ERROR', '1': 'ERROR', '2': 'ERROR', '3': 'ERROR',
                                   '4': 'WARN', '5': 'INFO', '6': 'INFO', '7': 'DEBUG'}
                    severity = severity_map.get(str(priority), 'INFO')
                    
                    if not self._should_include_severity(severity):
                        continue
                    
                    # Format content with context (same as incremental)
                    unit = entry.get('_SYSTEMD_UNIT', '')
                    identifier = entry.get('SYSLOG_IDENTIFIER', '')
                    pid = entry.get('_PID', '')
                    
                    # Build context prefix
                    context_parts = []
                    if unit:
                        context_parts.append(unit)
                    if identifier and pid:
                        context_parts.append(f"{identifier}[{pid}]")
                    elif identifier:
                        context_parts.append(identifier)
                    
                    if context_parts:
                        formatted_content = f"[{'] ['.join(context_parts)}]: {message.strip()}"
                    else:
                        formatted_content = message.strip()
                    
                    entries.append(LogEntry(
                        log_source='journal',
                        log_timestamp=timestamp,
                        content=formatted_content,
                        severity=severity
                    ))
                    
                    # Update cursor from this entry
                    last_cursor = entry.get('__CURSOR', last_cursor)
                    
                except json.JSONDecodeError:
                    continue
            
            # Set cursor for future incremental collection
            if last_cursor:
                self.cursors['journal']['cursor'] = last_cursor
                self.cursors['journal']['last_timestamp'] = int(time.time())
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect journal history: {e}")

    def _collect_syslog_history(self) -> List[LogEntry]:
        """Collect last 1000 lines from syslog file (first run)."""
        try:
            syslog_file = Path('/var/log/syslog')
            if not syslog_file.exists():
                raise Exception("/var/log/syslog does not exist")
            
            # Read last 1000 lines from file
            with open(syslog_file, 'r') as f:
                lines = f.readlines()
            
            # Crop to last 1000 lines
            if len(lines) > 1000:
                lines = lines[-1000:]
                self.logger.info(f"syslog history cropped to last 1000 lines")
            
            entries = []
            
            for line in lines:
                if not line.strip():
                    continue
                    
                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue
                
                # Parse actual syslog timestamp
                parsed_timestamp = self._parse_syslog_timestamp(line)
                if parsed_timestamp is None:
                    # No timestamp found - skip this entry (fail-fast)
                    continue
                    
                entries.append(LogEntry(
                    log_source='syslog',
                    log_timestamp=parsed_timestamp,
                    content=self._strip_syslog_timestamp(line),
                    severity=severity
                ))
            
            # Set cursor for future incremental collection
            stat = syslog_file.stat()
            self.cursors['syslog']['byte_offset'] = stat.st_size
            self.cursors['syslog']['inode'] = stat.st_ino
            self.cursors['syslog']['last_timestamp'] = int(time.time())
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect syslog history: {e}")

    def _collect_vast_history(self) -> List[LogEntry]:
        """Collect last 1000 lines from vast log file (first run)."""
        try:
            vast_file = Path('/var/lib/vastai_kaalia/kaalia.log')
            if not vast_file.exists():
                raise Exception("/var/lib/vastai_kaalia/kaalia.log does not exist")
            
            # Read last 1000 lines from file
            with open(vast_file, 'r') as f:
                lines = f.readlines()
            
            # Crop to last 1000 lines
            if len(lines) > 1000:
                lines = lines[-1000:]
                self.logger.info(f"vast history cropped to last 1000 lines")
            
            entries = []
            
            for line in lines:
                if not line.strip():
                    continue
                    
                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue
                
                # Parse actual vast timestamp
                parsed_timestamp = self._parse_vast_timestamp(line)
                if parsed_timestamp is None:
                    # No timestamp found - skip this entry (fail-fast)
                    continue
                    
                entries.append(LogEntry(
                    log_source='vast',
                    log_timestamp=parsed_timestamp,
                    content=self._strip_vast_metadata(line),
                    severity=severity
                ))
            
            # Set cursor for future incremental collection
            stat = vast_file.stat()
            self.cursors['vast']['byte_offset'] = stat.st_size
            self.cursors['vast']['inode'] = stat.st_ino
            self.cursors['vast']['last_timestamp'] = int(time.time())
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect vast history: {e}")


# ============================================================================
# NEW REFACTORED LOG EXPORTERS - Inheritance-based Architecture
# ============================================================================

class BaseLogExporter:
    """Base class for log exporters with common functionality."""
    
    def __init__(self, auth_dir: Path, config: Optional[Dict] = None):
        self.auth_dir = Path(auth_dir)
        self.cursors_file = self.auth_dir / "log-cursors.json"
        self.config = config or {}
        self.logger = logging.getLogger(f"dcmon.{self.__class__.__name__.lower()}")
        
        # Configuration
        log_config = self.config.get('log_monitoring', {})
        self.enabled = log_config.get('enabled', False)
        self.max_lines_per_cycle = log_config.get('max_lines_per_cycle', 50)
        self.severity_filter = log_config.get('severity_filter', 'WARN')
        self.enabled_sources = log_config.get('sources', ['dmesg', 'journal'])
        
        # Each exporter has a source_name (defined in children)
        self.source_name = getattr(self, 'source_name', 'unknown')
    
    def is_enabled(self) -> bool:
        """Check if this log source is enabled and available."""
        return (self.enabled and 
                self.source_name in self.enabled_sources and 
                self.is_available())
    
    def get_cursor_key(self) -> str:
        """Get the cursor key for this exporter."""
        return self.source_name
    
    def _parse_severity(self, line: str) -> str:
        """Parse severity level from log line."""
        line_lower = line.lower()
        if any(word in line_lower for word in ['error', 'err', 'fatal', 'fail', 'critical']):
            return 'ERROR'
        elif any(word in line_lower for word in ['warn', 'warning']):
            return 'WARN'  
        elif any(word in line_lower for word in ['debug']):
            return 'DEBUG'
        else:
            return 'INFO'  # Default to INFO for all unrecognized patterns
    
    def _should_include_severity(self, severity: str) -> bool:
        """Check if severity should be included based on filter."""
        severity_levels = {'DEBUG': 0, 'INFO': 1, 'WARN': 2, 'ERROR': 3}
        filter_level = severity_levels.get(self.severity_filter, 2)
        entry_level = severity_levels.get(severity, 0)
        return entry_level >= filter_level
    
    # Abstract methods to be implemented by children
    def is_available(self) -> bool:
        """Check if the log source is available."""
        raise NotImplementedError("Subclasses must implement is_available()")
    
    def collect_incremental(self, cursors: Dict) -> List[LogEntry]:
        """Collect new log entries since last cursor position."""
        raise NotImplementedError("Subclasses must implement collect_incremental()")
    
    def collect_history(self, cursors: Dict) -> List[LogEntry]:
        """Collect historical log entries (first run)."""
        raise NotImplementedError("Subclasses must implement collect_history()")
    
    def update_cursor(self, cursors: Dict, **cursor_data) -> None:
        """Update cursor data for this log source."""
        cursors[self.source_name] = cursor_data


class VastLogExporter(BaseLogExporter):
    """Vast.ai log exporter for /var/lib/vastai_kaalia/kaalia.log."""
    
    source_name = "vast"
    
    def is_available(self) -> bool:
        """Check if vast log file exists."""
        return Path('/var/lib/vastai_kaalia/kaalia.log').exists()
    
    def collect_incremental(self, cursors: Dict) -> List[LogEntry]:
        """Collect new vast log entries using file position tracking."""
        try:
            vast_file = Path('/var/lib/vastai_kaalia/kaalia.log')
            if not vast_file.exists():
                return []
            
            # Handle missing cursor (first run for this log source)
            if self.source_name not in cursors:
                return self.collect_history(cursors)
            
            cursor = cursors[self.source_name]
            stat = vast_file.stat()
            
            # Check for log rotation (inode changed)
            if cursor['inode'] != 0 and cursor['inode'] != stat.st_ino:
                cursor['byte_offset'] = 0
                cursor['inode'] = stat.st_ino
            
            # Read new content
            with open(vast_file, 'r') as f:
                f.seek(cursor['byte_offset'])
                new_content = f.read()
                new_offset = f.tell()
            
            if not new_content.strip():
                return []
            
            entries = []
            for line in new_content.strip().split('\n'):
                if not line.strip():
                    continue
                    
                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue
                
                parsed_timestamp = self._parse_vast_timestamp(line)
                if parsed_timestamp is None:
                    continue
                    
                entries.append(LogEntry(
                    log_source=self.source_name,
                    log_timestamp=parsed_timestamp,
                    content=self._strip_vast_metadata(line),
                    severity=severity
                ))
            
            # Update cursor
            self.update_cursor(cursors, 
                              byte_offset=new_offset, 
                              inode=stat.st_ino, 
                              last_timestamp=int(time.time()))
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect vast incremental: {e}")
    
    def collect_history(self, cursors: Dict) -> List[LogEntry]:
        """Collect last 1000 lines from vast log file (first run)."""
        try:
            vast_file = Path('/var/lib/vastai_kaalia/kaalia.log')
            if not vast_file.exists():
                raise Exception("/var/lib/vastai_kaalia/kaalia.log does not exist")
            
            # Read last 1000 lines from file
            with open(vast_file, 'r') as f:
                lines = f.readlines()
            
            # Crop to last 1000 lines
            if len(lines) > 1000:
                lines = lines[-1000:]
                self.logger.info(f"vast history cropped to last 1000 lines")
            
            entries = []
            for line in lines:
                if not line.strip():
                    continue
                    
                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue
                
                parsed_timestamp = self._parse_vast_timestamp(line)
                if parsed_timestamp is None:
                    continue
                    
                entries.append(LogEntry(
                    log_source=self.source_name,
                    log_timestamp=parsed_timestamp,
                    content=self._strip_vast_metadata(line),
                    severity=severity
                ))
            
            # Set cursor for future incremental collection
            stat = vast_file.stat()
            self.update_cursor(cursors,
                              byte_offset=stat.st_size,
                              inode=stat.st_ino,
                              last_timestamp=int(time.time()))
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect vast history: {e}")
    
    def _parse_vast_timestamp(self, line: str) -> Optional[int]:
        """Parse vast timestamp from format '[2025-09-07 15:33:07.798]' and convert to UTC."""
        import re
        from datetime import datetime, timezone
        try:
            match = re.match(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]', line.strip())
            if not match:
                return None
            
            timestamp_str = match.group(1)
            dt_local = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
            dt_local = dt_local.replace(tzinfo=datetime.now().astimezone().tzinfo)
            return int(dt_local.astimezone(timezone.utc).timestamp())
        except Exception as e:
            raise Exception(f"Failed to parse vast timestamp from '{line[:50]}...': {e}")
    
    def _strip_vast_metadata(self, line: str) -> str:
        """Strip timestamp and metadata from vast line, keeping only message content."""
        import re
        match = re.match(r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] \[Kaalia\] \[(?:info|warn|error)\] P\d+\s+(.*)', line.strip())
        if match:
            return match.group(1)
        return line.strip()


class SyslogExporter(BaseLogExporter):
    """System syslog exporter for /var/log/syslog."""
    
    source_name = "syslog"
    
    def is_available(self) -> bool:
        """Check if syslog file exists."""
        return Path('/var/log/syslog').exists()
    
    def collect_incremental(self, cursors: Dict) -> List[LogEntry]:
        """Collect new syslog entries using file position tracking."""
        try:
            syslog_file = Path('/var/log/syslog')
            if not syslog_file.exists():
                return []
            
            # Handle missing cursor (first run for this log source)
            if self.source_name not in cursors:
                return self.collect_history(cursors)
            
            cursor = cursors[self.source_name]
            stat = syslog_file.stat()
            
            # Check for log rotation (inode changed)
            if cursor['inode'] != 0 and cursor['inode'] != stat.st_ino:
                cursor['byte_offset'] = 0
                cursor['inode'] = stat.st_ino
            
            # Read new content
            with open(syslog_file, 'r') as f:
                f.seek(cursor['byte_offset'])
                new_content = f.read()
                new_offset = f.tell()
            
            if not new_content.strip():
                return []
            
            entries = []
            for line in new_content.strip().split('\n'):
                if not line.strip():
                    continue
                    
                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue
                
                parsed_timestamp = self._parse_syslog_timestamp(line)
                if parsed_timestamp is None:
                    continue
                    
                entries.append(LogEntry(
                    log_source=self.source_name,
                    log_timestamp=parsed_timestamp,
                    content=self._strip_syslog_timestamp(line),
                    severity=severity
                ))
            
            # Update cursor
            self.update_cursor(cursors, 
                              byte_offset=new_offset, 
                              inode=stat.st_ino, 
                              last_timestamp=int(time.time()))
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect syslog incremental: {e}")
    
    def collect_history(self, cursors: Dict) -> List[LogEntry]:
        """Collect last 1000 lines from syslog file (first run)."""
        try:
            syslog_file = Path('/var/log/syslog')
            if not syslog_file.exists():
                raise Exception("/var/log/syslog does not exist")
            
            # Read last 1000 lines from file
            with open(syslog_file, 'r') as f:
                lines = f.readlines()
            
            # Crop to last 1000 lines
            if len(lines) > 1000:
                lines = lines[-1000:]
                self.logger.info(f"syslog history cropped to last 1000 lines")
            
            entries = []
            for line in lines:
                if not line.strip():
                    continue
                    
                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue
                
                parsed_timestamp = self._parse_syslog_timestamp(line)
                if parsed_timestamp is None:
                    continue
                    
                entries.append(LogEntry(
                    log_source=self.source_name,
                    log_timestamp=parsed_timestamp,
                    content=self._strip_syslog_timestamp(line),
                    severity=severity
                ))
            
            # Set cursor for future incremental collection
            stat = syslog_file.stat()
            self.update_cursor(cursors,
                              byte_offset=stat.st_size,
                              inode=stat.st_ino,
                              last_timestamp=int(time.time()))
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect syslog history: {e}")
    
    def _parse_syslog_timestamp(self, line: str) -> Optional[int]:
        """Parse syslog timestamp from standard format 'Sep  7 13:14:25' and convert to UTC."""
        import re
        from datetime import datetime, timezone
        try:
            match = re.match(r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})', line.strip())
            if not match:
                return None
            
            timestamp_str = match.group(1)
            current_year = datetime.now().year
            full_timestamp = f"{current_year} {timestamp_str}"
            
            dt_local = datetime.strptime(full_timestamp, "%Y %b %d %H:%M:%S")
            dt_local = dt_local.replace(tzinfo=datetime.now().astimezone().tzinfo)
            return int(dt_local.astimezone(timezone.utc).timestamp())
        except Exception as e:
            raise Exception(f"Failed to parse syslog timestamp from '{line[:50]}...': {e}")
    
    def _strip_syslog_timestamp(self, line: str) -> str:
        """Strip timestamp from syslog line, keeping only message content."""
        import re
        match = re.match(r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(.*)', line.strip())
        if match:
            return match.group(3)
        return line.strip()


class DmesgExporter(BaseLogExporter):
    """Kernel dmesg exporter."""
    
    source_name = "dmesg"
    
    def __init__(self, auth_dir: Path, config: Optional[Dict] = None):
        super().__init__(auth_dir, config)
        # Cache boot time once - only changes on system reboot (which restarts client)
        self.boot_time = self._get_boot_time() if self.is_enabled() else None
    
    def is_available(self) -> bool:
        """dmesg is always available on Linux systems."""
        return True
    
    def collect_incremental(self, cursors: Dict) -> List[LogEntry]:
        """Collect new dmesg entries using line count tracking."""
        try:
            import subprocess
            
            # Handle missing cursor (first run for this log source)
            if self.source_name not in cursors:
                return self.collect_history(cursors)
            
            cursor = cursors[self.source_name]
            
            # Get current dmesg output
            result = subprocess.run(['dmesg'], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise Exception(f"dmesg command failed: {result.stderr}")
            
            lines = result.stdout.strip().split('\n')
            last_line = cursor.get('last_line', 0)
            
            # Get new lines
            if len(lines) <= last_line:
                return []
            
            new_lines = lines[last_line:]
            entries = []
            
            for line in new_lines:
                if not line.strip():
                    continue
                    
                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue
                
                parsed_timestamp = self._parse_dmesg_timestamp(line)
                if parsed_timestamp is None:
                    continue
                    
                entries.append(LogEntry(
                    log_source=self.source_name,
                    log_timestamp=parsed_timestamp,
                    content=line.strip(),
                    severity=severity
                ))
            
            # Update cursor
            self.update_cursor(cursors,
                              last_line=len(lines),
                              last_timestamp=int(time.time()))
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect dmesg incremental: {e}")
    
    def collect_history(self, cursors: Dict) -> List[LogEntry]:
        """Collect full dmesg history since boot (first run)."""
        try:
            import subprocess
            
            result = subprocess.run(['dmesg'], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise Exception(f"dmesg command failed: {result.stderr}")
            
            lines = result.stdout.strip().split('\n')
            
            # Crop to last 1000 lines if exceeding
            if len(lines) > 1000:
                lines = lines[-1000:]
                self.logger.info(f"dmesg history cropped to last 1000 lines")
            
            entries = []
            for line in lines:
                if not line.strip():
                    continue
                    
                severity = self._parse_severity(line)
                if not self._should_include_severity(severity):
                    continue
                
                parsed_timestamp = self._parse_dmesg_timestamp(line)
                if parsed_timestamp is None:
                    continue
                    
                entries.append(LogEntry(
                    log_source=self.source_name,
                    log_timestamp=parsed_timestamp,
                    content=line.strip(),
                    severity=severity
                ))
            
            # Set cursor to total line count for future incremental collection
            self.update_cursor(cursors,
                              last_line=len(result.stdout.strip().split('\n')),
                              last_timestamp=int(time.time()))
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect dmesg history: {e}")
    
    def _get_boot_time(self) -> int:
        """Get system boot time from /proc/stat."""
        try:
            with open('/proc/stat', 'r') as f:
                for line in f:
                    if line.startswith('btime'):
                        return int(line.split()[1])
            raise Exception("btime not found in /proc/stat")
        except Exception as e:
            raise Exception(f"Failed to get boot time: {e}")
    
    def _parse_dmesg_timestamp(self, line: str) -> Optional[int]:
        """Parse dmesg timestamp from kernel line format [12345.67]."""
        import re
        try:
            match = re.match(r'^\[\s*(\d+\.\d+)\]', line.strip())
            if not match:
                return None
            
            kernel_seconds = float(match.group(1))
            return self.boot_time + int(kernel_seconds)
        except Exception as e:
            raise Exception(f"Failed to parse dmesg timestamp from '{line[:50]}...': {e}")


class JournalExporter(BaseLogExporter):
    """Systemd journal exporter."""
    
    source_name = "journal"
    
    def is_available(self) -> bool:
        """Check if journalctl is available."""
        import subprocess
        try:
            subprocess.run(['journalctl', '--version'], capture_output=True, timeout=5)
            return True
        except:
            return False
    
    def collect_incremental(self, cursors: Dict) -> List[LogEntry]:
        """Collect new journal entries using systemd cursor."""
        try:
            import subprocess
            import json
            
            # Handle missing cursor (first run for this log source)
            if self.source_name not in cursors:
                return self.collect_history(cursors)
            
            cursor = cursors[self.source_name]
            cmd = ['journalctl', '--output=json', '--no-pager']
            
            # Use cursor if available
            if cursor.get('cursor'):
                cmd.extend(['--after-cursor', cursor['cursor']])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return []
            
            entries = []
            last_cursor = cursor.get('cursor', "")
            
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                    
                try:
                    entry = json.loads(line)
                    message = entry.get('MESSAGE', '')
                    if not message:
                        continue
                    
                    # Extract timestamp
                    timestamp_usec = int(entry.get('__REALTIME_TIMESTAMP', 0))
                    timestamp = timestamp_usec // 1000000  # Convert to seconds
                    
                    # Extract severity
                    priority = entry.get('PRIORITY', '6')  # Default to INFO
                    severity_map = {'0': 'ERROR', '1': 'ERROR', '2': 'ERROR', '3': 'ERROR',
                                   '4': 'WARN', '5': 'INFO', '6': 'INFO', '7': 'DEBUG'}
                    severity = severity_map.get(priority, 'INFO')
                    
                    if not self._should_include_severity(severity):
                        continue
                    
                    # Enhanced content with context
                    content = self._format_journal_content(entry, message)
                    
                    entries.append(LogEntry(
                        log_source=self.source_name,
                        log_timestamp=timestamp,
                        content=content,
                        severity=severity
                    ))
                    
                    # Update cursor
                    last_cursor = entry.get('__CURSOR', last_cursor)
                    
                except (json.JSONDecodeError, ValueError, KeyError):
                    continue
            
            # Update cursor
            if entries:  # Only update if we got new entries
                self.update_cursor(cursors,
                                  cursor=last_cursor,
                                  last_timestamp=int(time.time()))
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect journal incremental: {e}")
    
    def collect_history(self, cursors: Dict) -> List[LogEntry]:
        """Collect journal history (first run)."""
        try:
            import subprocess
            import json
            
            # Get last 1000 entries
            cmd = ['journalctl', '--output=json', '--no-pager', '--lines=1000']
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                raise Exception(f"journalctl command failed: {result.stderr}")
            
            entries = []
            last_cursor = ""
            entry_count = 0
            
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                    
                try:
                    entry = json.loads(line)
                    message = entry.get('MESSAGE', '')
                    if not message:
                        continue
                    
                    # Crop to 1000 entries max
                    entry_count += 1
                    if entry_count > 1000:
                        self.logger.info(f"journal history cropped to 1000 entries")
                        break
                    
                    # Extract timestamp
                    timestamp_usec = int(entry.get('__REALTIME_TIMESTAMP', 0))
                    timestamp = timestamp_usec // 1000000
                    
                    # Extract severity
                    priority = entry.get('PRIORITY', '6')
                    severity_map = {'0': 'ERROR', '1': 'ERROR', '2': 'ERROR', '3': 'ERROR',
                                   '4': 'WARN', '5': 'INFO', '6': 'INFO', '7': 'DEBUG'}
                    severity = severity_map.get(priority, 'INFO')
                    
                    if not self._should_include_severity(severity):
                        continue
                    
                    # Enhanced content with context
                    content = self._format_journal_content(entry, message)
                    
                    entries.append(LogEntry(
                        log_source=self.source_name,
                        log_timestamp=timestamp,
                        content=content,
                        severity=severity
                    ))
                    
                    last_cursor = entry.get('__CURSOR', last_cursor)
                    
                except (json.JSONDecodeError, ValueError, KeyError):
                    continue
            
            # Set cursor for future incremental collection
            if last_cursor:
                self.update_cursor(cursors,
                                  cursor=last_cursor,
                                  last_timestamp=int(time.time()))
            
            return entries
            
        except Exception as e:
            raise Exception(f"Failed to collect journal history: {e}")
    
    def _format_journal_content(self, entry: dict, message: str) -> str:
        """Format journal entry with enhanced context."""
        context_parts = []
        
        # Add systemd unit if available
        if entry.get('_SYSTEMD_UNIT'):
            context_parts.append(entry['_SYSTEMD_UNIT'])
        elif entry.get('UNIT'):
            context_parts.append(entry['UNIT'])
        
        # Add service name or identifier
        if entry.get('SYSLOG_IDENTIFIER'):
            identifier = entry['SYSLOG_IDENTIFIER']
            if entry.get('_PID'):
                identifier += f"[{entry['_PID']}]"
            context_parts.append(identifier)
        
        if context_parts:
            return f"[{'] ['.join(context_parts)}]: {message.strip()}"
        else:
            return message.strip()


class LogExporterManager:
    """Manager for coordinating multiple log exporters using inheritance pattern."""
    
    def __init__(self, auth_dir: Path, config: Optional[Dict] = None):
        self.auth_dir = Path(auth_dir)
        self.cursors_file = self.auth_dir / "log-cursors.json"
        self.config = config or {}
        self.logger = logging.getLogger("dcmon.log_exporter_manager")
        
        # Load cursors on initialization
        self.cursors = self._load_cursors()
        
        # Configuration
        log_config = self.config.get('log_monitoring', {})
        self.enabled = log_config.get('enabled', False)
        self.max_lines_per_cycle = log_config.get('max_lines_per_cycle', 50)
        self.enabled_sources = log_config.get('sources', ['dmesg', 'journal'])
        
        # Initialize all available exporters
        self.exporters = {
            'dmesg': DmesgExporter(auth_dir, config),
            'journal': JournalExporter(auth_dir, config), 
            'syslog': SyslogExporter(auth_dir, config),
            'vast': VastLogExporter(auth_dir, config)
        }
        
        # Log availability status
        for name, exporter in self.exporters.items():
            if exporter.is_enabled():
                self.logger.debug(f"{name} log exporter enabled and available")
            elif name in self.enabled_sources:
                self.logger.info(f"{name} logs disabled - not available")
    
    def collect_new_logs(self) -> List[LogEntry]:
        """Collect new log entries from all enabled exporters."""
        if not self.enabled:
            return []
        
        is_first_run = self._is_first_run()
        if is_first_run:
            self.logger.info("First run detected - collecting extended log history")
        
        all_logs = []
        
        # Collect from each enabled exporter
        for name, exporter in self.exporters.items():
            if not exporter.is_enabled():
                continue
                
            try:
                if is_first_run:
                    logs = exporter.collect_history(self.cursors)
                else:
                    logs = exporter.collect_incremental(self.cursors)
                
                all_logs.extend(logs)
                self.logger.debug(f"Collected {len(logs)} entries from {name}")
                
            except Exception as e:
                self.logger.error(f"Failed to collect {name} logs: {e}")
                # Continue with other exporters (fail-fast per exporter, not globally)
        
        # Apply size limit (different for first run vs normal)
        max_entries = 3000 if is_first_run else self.max_lines_per_cycle
        if len(all_logs) > max_entries:
            # Keep most recent entries
            all_logs = sorted(all_logs, key=lambda x: x.log_timestamp)[-max_entries:]
            self.logger.info(f"Log collection limited to {max_entries} most recent entries")
        
        # Save cursors after collection
        if all_logs:  # Only save if we collected something
            self._save_cursors()
        
        return all_logs
    
    def _load_cursors(self) -> Dict:
        """Load cursor positions from persistent storage."""
        # Default cursors for all possible sources
        default_cursors = {
            "dmesg": {"last_line": 0, "last_timestamp": 0},
            "journal": {"cursor": "", "last_timestamp": 0},
            "syslog": {"byte_offset": 0, "inode": 0, "last_timestamp": 0},
            "vast": {"byte_offset": 0, "inode": 0, "last_timestamp": 0}
        }
        
        try:
            if self.cursors_file.exists():
                with open(self.cursors_file, 'r') as f:
                    loaded_cursors = json.load(f)
                # Merge loaded cursors with defaults (handles missing keys)
                default_cursors.update(loaded_cursors)
        except Exception as e:
            self.logger.error(f"Error loading cursors: {e}")
        
        return default_cursors
    
    def _save_cursors(self) -> None:
        """Save cursor positions to persistent storage."""
        try:
            self.auth_dir.mkdir(parents=True, exist_ok=True)
            with open(self.cursors_file, 'w') as f:
                json.dump(self.cursors, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving cursors: {e}")
    
    def _is_first_run(self) -> bool:
        """Check if this is the first run (no cursor file or empty cursors)."""
        if not self.cursors_file.exists():
            return True
        
        # Check if cursors are at default/empty state
        default_cursors = {
            "dmesg": {"last_line": 0, "last_timestamp": 0},
            "journal": {"cursor": "", "last_timestamp": 0},
            "syslog": {"byte_offset": 0, "inode": 0, "last_timestamp": 0},
            "vast": {"byte_offset": 0, "inode": 0, "last_timestamp": 0}
        }
        return self.cursors == default_cursors
