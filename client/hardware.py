"""
Hardware detection utilities for dcmon client.

Provides functions to detect system hardware specifications including:
- CPU, GPU, RAM, motherboard
- Storage drives
- Machine identifiers
- Vast.ai specific information
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


def detect_motherboard() -> Optional[str]:
    """Detect motherboard name from DMI."""
    try:
        vendor_path = Path("/sys/class/dmi/id/board_vendor")
        name_path = Path("/sys/class/dmi/id/board_name")

        vendor = vendor_path.read_text().strip() if vendor_path.exists() else ""
        name = name_path.read_text().strip() if name_path.exists() else ""

        if vendor and name:
            return f"{vendor} {name}"
        elif name:
            return name
        elif vendor:
            return vendor
        return None
    except Exception:
        return None


def detect_cpu() -> Tuple[Optional[str], Optional[int]]:
    """Detect CPU name and core count from /proc/cpuinfo."""
    try:
        cpu_name = None
        core_count = 0

        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("model name") and cpu_name is None:
                    cpu_name = line.split(":", 1)[1].strip()
                elif line.startswith("processor"):
                    core_count += 1

        return cpu_name, core_count if core_count > 0 else None
    except Exception:
        return None, None


def detect_memory() -> Optional[int]:
    """Detect total RAM in GB from /proc/meminfo."""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    gb = round(kb / 1024 / 1024)
                    return gb
        return None
    except Exception:
        return None


def detect_gpu() -> Tuple[Optional[str], Optional[int]]:
    """Detect primary GPU name and count."""
    try:
        # Try nvidia-smi first
        result = os.popen("nvidia-smi --query-gpu=name --format=csv,noheader,nounits 2>/dev/null").read().strip()
        if result:
            gpus = result.split('\n')
            gpu_count = len(gpus)
            primary_gpu = gpus[0].strip()
            return primary_gpu, gpu_count

        # Fallback to lspci for other GPUs
        result = os.popen("lspci | grep -i vga 2>/dev/null").read().strip()
        if result:
            lines = result.split('\n')
            gpu_count = len(lines)
            # Extract GPU name from first line
            if ':' in lines[0]:
                primary_gpu = lines[0].split(':', 1)[1].strip()
                return primary_gpu, gpu_count

        return None, None
    except Exception:
        return None, None


def detect_machine_id() -> str:
    """Read machine ID from /etc/machine-id."""
    return Path("/etc/machine-id").read_text().strip()


def get_size_from_str(size_str: str) -> Optional[int]:
    """Parse size string (e.g., '500G', '1.5T') to GB as integer."""
    size_gb = None
    if size_str.endswith('G'):
        size_value = size_str[:-1].replace(',', '.')
        size_gb = int(float(size_value))
    elif size_str.endswith('T'):
        size_value = size_str[:-1].replace(',', '.')
        size_gb = int(float(size_value) * 1024)
    elif size_str.endswith('M'):
        size_value = size_str[:-1].replace(',', '.')
        size_gb = int(float(size_value) / 1024)
    return size_gb


def detect_all_drives() -> List[Dict[str, Any]]:
    """Detect all drives in the system."""
    drives = []
    try:
        # Get all physical drives
        result = os.popen("lsblk -d -n -o NAME,SIZE,MODEL 2>/dev/null | grep -E '^(sd|nvme|hd)'").read().strip()

        if result:
            for line in result.split('\n'):
                if line.strip():
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        device = parts[0]
                        size_str = parts[1]
                        model = ' '.join(parts[2:]) if len(parts) > 2 else None

                        # Parse size to GB (handle both comma and dot decimal separators)
                        size_gb = get_size_from_str(size_str)

                        drives.append({
                            "device": device,
                            "model": model,
                            "size_gb": size_gb
                        })

        return drives
    except Exception as e:
        logger.debug(f"detect_all_drives exception: {e}")
        return []


def create_hardware_hash(hardware_data: Dict[str, Any]) -> str:
    """Create consistent hash from hardware data for change detection."""
    # Create a consistent representation for hashing
    hash_data = {
        "mdb_name": hardware_data.get("mdb_name", ""),
        "cpu_name": hardware_data.get("cpu_name", ""),
        "cpu_cores": hardware_data.get("cpu_cores", 0),
        "ram_gb": hardware_data.get("ram_gb", 0),
        "gpu_name": hardware_data.get("gpu_name", ""),
        "gpu_count": hardware_data.get("gpu_count", 0),
        # Sort drives by device name for consistent ordering
        "drives": sorted(hardware_data.get("drives", []), key=lambda x: x.get("device", ""))
    }

    # Convert to JSON string with sorted keys for consistency
    hash_string = json.dumps(hash_data, sort_keys=True, separators=(',', ':'))

    # Create SHA256 hash
    return hashlib.sha256(hash_string.encode()).hexdigest()


def detect_vast_machine_id() -> Optional[str]:
    """Detect Vast.ai machine ID from /var/lib/vastai_kaalia/machine_id."""
    try:
        vast_machine_id_path = Path("/var/lib/vastai_kaalia/machine_id")
        if vast_machine_id_path.exists():
            machine_id = vast_machine_id_path.read_text().strip()
            return machine_id if machine_id else None
        return None
    except Exception:
        return None


def detect_vast_port_range() -> Optional[str]:
    """Detect Vast.ai port range from /var/lib/vastai_kaalia/host_port_range."""
    try:
        vast_port_range_path = Path("/var/lib/vastai_kaalia/host_port_range")
        if vast_port_range_path.exists():
            port_range = vast_port_range_path.read_text().strip()
            return port_range if port_range else None
        return None
    except Exception:
        return None


def detect_hardware() -> Dict[str, Any]:
    """Detect all hardware information."""
    machine_id = detect_machine_id()
    cpu_name, cpu_cores = detect_cpu()
    gpu_name, gpu_count = detect_gpu()

    hardware = {
        "machine_id": machine_id,  # Required for registration
        "mdb_name": detect_motherboard(),
        "cpu_name": cpu_name,
        "cpu_cores": cpu_cores,
        "gpu_name": gpu_name,
        "gpu_count": gpu_count,
        "ram_gb": detect_memory(),
        "drives": detect_all_drives(),  # New: all drives data
    }

    # Add hardware hash (exclude machine_id from hash since it's system ID, not hardware)
    hardware["hw_hash"] = create_hardware_hash(hardware)

    return hardware
