#!/usr/bin/env python3
"""
dcmon client

Flow:
- Credentials live under --auth-dir (default /etc/dcmon): client.key, client.pub, client_token
- If client_token is missing:
    * ensure keys exist (generate if needed)
    * prompt for admin token (secure input, not stored)
    * register with server using admin token + cryptographic proof
    * save returned client_token for future use
- If client_token exists:
    * collect lightweight system metrics (no external deps)
    * POST /api/metrics with Authorization: Bearer <client_token>
    * loop every --interval seconds (or --once for a single send)

Admin token is only used during initial registration and never stored on client.
"""

import argparse
import asyncio
import getpass
import hashlib
import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

# Local auth helper (keys + registration request)
try:
    # when run as module
    from .auth import ClientAuth, setup_client_auth
    from .exporters import OSMetricsExporter, IpmiExporter, AptExporter, NvmeExporter, NvsmiExporter, BMCFanExporter
except ImportError:
    # when run as script from project root
    from auth import ClientAuth, setup_client_auth
    from exporters import OSMetricsExporter, IpmiExporter, AptExporter, NvmeExporter, NvsmiExporter, BMCFanExporter


LOG = logging.getLogger("dcmon.client")


# ---------------- Configuration ----------------

@dataclass
class ClientConfig:
    """Client configuration with defaults"""
    auth_dir: str = "/etc/dcmon"
    server: str = "http://127.0.0.1:8000"
    interval: int = 30
    log_level: str = "INFO"
    once: bool = False
    registration: bool = False
    
    @classmethod
    def from_file(cls, config_path: Path) -> "ClientConfig":
        """Load configuration from YAML file"""
        if not config_path.exists():
            LOG.debug(f"Config file not found: {config_path}, using defaults")
            return cls()
        
        try:
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
            LOG.debug(f"Loaded config from {config_path}: {data}")
            return cls(**data)
        except Exception as e:
            LOG.warning(f"Failed to load config from {config_path}: {e}, using defaults")
            return cls()
    
    def override_with_args(self, args: argparse.Namespace) -> "ClientConfig":
        """Override config with command line arguments if provided"""
        # Direct override - CLI args take precedence
        self.auth_dir = args.auth_dir
        self.server = args.server  
        self.interval = args.interval
        self.log_level = args.log_level
        self.once = args.once
        self.registration = args.registration
        return self


# ---------------- HTTP helpers ----------------

def _post_json(url: str, data: Dict[str, Any], headers: Dict[str, str], timeout: int = 10) -> Dict[str, Any]:
    body = json.dumps(data).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = Request(url, data=body, headers=hdrs, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


# ---------------- Registration UX ----------------

def ensure_registration_request(auth: ClientAuth, auth_dir: Path, hostname: str) -> Path:
    """
    Create <auth_dir>/registration_request.json with the signed request and return its path.
    """
    req = auth.create_registration_request(hostname=hostname)
    if not req:
        raise SystemExit("ERROR: failed to create registration request (keys missing or crypto error).")
    out_path = auth_dir / "registration_request.json"
    out_path.write_text(json.dumps(req, indent=2))
    try:
        out_path.chmod(0o600)
    except Exception:
        pass
    return out_path


def print_registration_instructions(server_base: str, req_path: Path, auth_dir: Path):
    server_base = server_base.rstrip("/")
    print(
        f"\n⚠️  No client token found in {auth_dir}.\n"
        f"   A registration request has been written to:\n"
        f"     {req_path}\n\n"
        f"➜ Ask an administrator to register this client:\n"
        f"   curl -X POST {server_base}/api/clients/register \\\n"
        f"        -H \"Authorization: Bearer <ADMIN_TOKEN>\" \\\n"
        f"        -H \"Content-Type: application/json\" \\\n"
        f"        --data-binary @{req_path}\n\n"
        f"   The server will return JSON with a client_token. Save it to:\n"
        f"     {auth_dir}/client_token    (chmod 600)\n\n"
        f"   Then re-run this client.\n"
    )


# ---------------- Hardware detection ----------------

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

def detect_cpu() -> tuple[Optional[str], Optional[int]]:
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

def detect_gpu() -> tuple[Optional[str], Optional[int]]:
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

def detect_all_drives() -> List[Dict[str, Any]]:
    """Detect all drives in the system."""
    drives = []
    try:
        # Get all physical drives
        result = os.popen("lsblk -d -n -o NAME,SIZE,MODEL 2>/dev/null | grep -E '^(sd|nvme|hd)'").read().strip()
        LOG.debug(f"lsblk all drives result: '{result}'")
        
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
        
        LOG.debug(f"detected all drives: {drives}")
        return drives
    except Exception as e:
        LOG.debug(f"detect_all_drives exception: {e}")
        return []


def get_size_from_str(size_str: str) -> Any:
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
    
    LOG.debug(f"detect_hardware result: {hardware}")
    return hardware

# ---------------- Metrics collection (stdlib only) ----------------

def _now() -> int:
    return int(time.time())


class MetricsCollector:
    """Manages metrics collection from all exporters with singleton pattern"""
    
    def __init__(self, hw_info: Dict = None):
        """Initialize all exporters once during startup"""
        self.hw_info = hw_info or {}
        LOG.info("Initializing metrics exporters...")
        self.exporters = [
            OSMetricsExporter(),
            IpmiExporter(),
            AptExporter(), 
            NvmeExporter(),
            NvsmiExporter(),
            BMCFanExporter(hw_info=self.hw_info),
        ]
        LOG.info(f"Initialized {len(self.exporters)} metrics exporters")
    
    async def collect_metrics(self) -> List[Dict[str, Any]]:
        """
        Collect metrics from all initialized exporters.
        Returns metrics in server's expected schema format.
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
                LOG.warning(f"Failed to collect metrics from {exporter.__class__.__name__}: {e}")
                continue
        
        return all_metrics




def send_metrics(server_base: str, client_token: str, metrics: List[Dict[str, Any]], hw_hash: Optional[str] = None) -> Dict[str, Any]:
    if not metrics:
        return {"received": 0, "inserted": 0}
    url = server_base.rstrip("/") + "/api/metrics"
    headers = {"Authorization": f"Bearer {client_token}"}
    data = {"metrics": metrics}
    if hw_hash:
        data["hw_hash"] = hw_hash
    return _post_json(url, data, headers)


def register_client_interactively(auth: ClientAuth, server_base: str, hostname: str) -> str:
    """
    Prompt for admin token and register client with server.
    Returns client_token on success, raises SystemExit on failure.
    """
    print(f"\n🔐 Client registration required for {hostname}")
    print("Please enter the admin token to register this client with the server.")
    
    try:
        admin_token = getpass.getpass("Admin token: ").strip()
    except (EOFError, KeyboardInterrupt):
        # Fallback for non-interactive environments (testing/IDE)
        print("\nFallback to regular input (dev mode):")
        admin_token = input("Admin token: ").strip()
    
    if not admin_token:
        raise SystemExit("ERROR: Admin token cannot be empty.")
    
    # Create registration request
    req = auth.create_registration_request(hostname=hostname)
    if not req:
        raise SystemExit("ERROR: Failed to create registration request (keys missing or crypto error).")
    
    # Detect hardware information
    print("🔍 Detecting hardware specifications...")
    hardware = detect_hardware()
    
    # Add hardware info to registration request
    req.update(hardware)
    
    # Add admin token to request (only in memory)  
    req["admin_token"] = admin_token
    
    # Send registration request
    url = server_base.rstrip("/") + "/api/clients/register"
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    try:
        response = _post_json(url, req, headers)
        client_token = response.get("client_token")
        if not client_token:
            raise SystemExit("ERROR: Server did not return client_token in registration response.")
        
        print("✅ Client registered successfully!")
        LOG.info("Client registered with server: %s", server_base)
        return client_token
        
    except HTTPError as e:
        try:
            error_msg = e.read().decode("utf-8")
        except Exception:
            error_msg = str(e)
        raise SystemExit(f"ERROR: Registration failed (HTTP {getattr(e, 'code', '?')}): {error_msg}")
    
    except URLError as e:
        raise SystemExit(f"ERROR: Failed to reach server: {e}")
    
    except Exception as e:
        raise SystemExit(f"ERROR: Registration failed: {e}")


# ---------------- Main ----------------

async def run_client(config: ClientConfig) -> None:
    # Configure auth helper (keys + token)
    auth_dir = Path(config.auth_dir)
    auth = setup_client_auth(auth_dir)
    if not auth:
        raise SystemExit(1)

    # Registration-only mode: print request JSON to stdout and exit
    if config.registration:
        req = auth.create_registration_request(socket.gethostname())
        if not req:
            raise SystemExit("ERROR: failed to create registration request.")
        print(json.dumps(req, indent=2))
        return

    # Ensure client token exists; otherwise register interactively
    token = auth.load_client_token()
    if not token:
        hostname = socket.gethostname()
        # Interactive registration with admin token prompt
        token = register_client_interactively(auth, config.server, hostname)
        # Save the client token for future use
        if not auth.save_client_token(token):
            raise SystemExit("ERROR: Failed to save client token after registration.")
        LOG.info("Client token saved successfully")

    # Generate hardware hash once for metrics sending
    hw_info = detect_hardware()
    hw_hash = hw_info.get("hw_hash")
    
    # Initialize metrics collector once (singleton exporters) with hardware info
    metrics_collector = MetricsCollector(hw_info=hw_info)
    
    # Metrics loop
    LOG.info("client starting; posting metrics to %s every %ss", config.server, config.interval)
    while True:
        try:
            batch = await metrics_collector.collect_metrics()
            if not batch:
                LOG.warning("no metrics collected")
            res = send_metrics(config.server, token, batch, hw_hash)
            LOG.debug("sent metrics: %s", res)
        except HTTPError as e:
            try:
                msg = e.read().decode("utf-8")
            except Exception:
                msg = str(e)
            LOG.error("HTTP %s error from server: %s", getattr(e, "code", "?"), msg)
        except URLError as e:
            LOG.error("failed to reach server: %s", e)
        except Exception as e:
            LOG.exception("unexpected error during metrics send: %s", e)

        if config.once:
            break
        await asyncio.sleep(max(1, config.interval))


def main():
    parser = argparse.ArgumentParser(description="dcmon client")
    parser.add_argument("--config", "-c", type=Path, default=Path("config.yaml"),
                        help="YAML configuration file (default: config.yaml)")
    parser.add_argument("--auth-dir", default="/etc/dcmon", dest="auth_dir",
                        help="directory for client credentials (private key, public key, client token)")
    parser.add_argument("--server", default="http://127.0.0.1:8000",
                        help="dcmon server base URL (e.g., http://server:8000)")
    parser.add_argument("--interval", type=int, default=30,
                        help="seconds between metric posts")
    parser.add_argument("--once", action="store_true",
                        help="send one metrics batch and exit")
    parser.add_argument("--registration", action="store_true",
                        help="print a registration request JSON to stdout and exit")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="logging level")
    args = parser.parse_args()

    # Load config: YAML first, then CLI overrides
    config = ClientConfig.from_file(args.config).override_with_args(args)
    
    # Configure logging
    logging.basicConfig(level=getattr(logging, config.log_level))
    LOG.info(f"dcmon client starting with config: server={config.server}, interval={config.interval}s")

    try:
        asyncio.run(run_client(config))
    except KeyboardInterrupt:
        print("\nInterrupted. Bye!")


if __name__ == "__main__":
    main()
