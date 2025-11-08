"""PSU (Power Supply Unit) metrics exporter.

Collects power supply metrics using ipmicfg for Supermicro systems.
Requires ipmicfg tool and root privileges.
"""

import asyncio
import logging
from typing import List, Dict

from .base import MetricsExporter, MetricPoint


def is_ipmicfg_available() -> bool:
    """
    Check if ipmicfg is available (requires root for PSU monitoring).
    Returns True if ipmicfg tools and BMC access are available.
    """
    import os
    import subprocess

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
