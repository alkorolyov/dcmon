"""Utility functions for exporters - hardware detection and availability checks"""
import logging
import os
import subprocess
from pathlib import Path


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

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.debug(f"ipmicfg availability: FAIL - {e}")
        return False
