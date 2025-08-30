# dcmon Client

The dcmon client is a lightweight monitoring agent that collects system metrics and sends them to the dcmon server.

## Features

### Core Metrics Collection
- **OS Metrics**: CPU load, memory usage, disk I/O, network I/O
- **Hardware Metrics**: IPMI sensors (temperature, power, fans)  
- **Storage Metrics**: NVMe drive health and performance
- **GPU Metrics**: NVIDIA GPU utilization, temperature, power
- **System Metrics**: APT package updates, reboot requirements

### Architecture
- **Modular Design**: Each metric type is a separate collector
- **Async Collection**: Non-blocking metrics gathering
- **Error Resilient**: Individual collector failures don't affect others
- **Configurable**: Enable/disable exporters via configuration

## Collected Metrics

### OS Metrics (23 total)
```
cpu_load_1m, cpu_load_5m, cpu_load_15m    # System load averages
cpu_usage_percent                          # CPU utilization
memory_total_bytes, memory_available_bytes # Memory stats
memory_used_bytes, memory_usage_percent    # Memory usage
disk_reads_total, disk_read_bytes_total    # Disk I/O per device
disk_writes_total, disk_write_bytes_total  # Disk I/O per device  
network_receive_bytes_total               # Network RX per interface
network_transmit_bytes_total              # Network TX per interface
```

### GPU Metrics (14 per GPU)
```
gpu_temperature                           # Temperature in °C
gpu_power_draw, gpu_power_limit          # Power consumption/limit
gpu_utilization_gpu, gpu_utilization_memory # GPU/memory utilization %
gpu_fan_speed                            # Fan speed %
gpu_clock_sm, gpu_clock_mem              # Clock speeds MHz
gpu_memory_usage                         # Memory usage %
gpu_ecc_errors_corrected/uncorrected     # ECC error counts
```

### IPMI Metrics (varies)
```
ipmi_temperature_celsius                 # Temperature sensors
ipmi_power_watts                        # Power consumption
ipmi_speed_rpm                          # Fan speeds
ipmi_volts, ipmi_amps                   # Electrical readings
```

### APT Metrics
```
apt_upgrades_pending                    # Pending package updates
apt_reboot_required                     # Reboot requirement flag
```

### NVMe Metrics (per drive)
```
nvme_temperature_celsius                # Drive temperature
nvme_available_spare_ratio              # Spare capacity
nvme_percentage_used_ratio              # Wear level
nvme_critical_warning_total             # Critical warnings
nvme_power_on_hours_total              # Operating hours
```

## Configuration

Default configuration in `/etc/dcmon/config.json`:
```json
{
  "server_url": "http://your-server.com:8000",
  "collection_interval": 30,
  "exporters": {
    "ipmi": true,
    "apt": true, 
    "nvme": true,
    "nvsmi": true
  }
}
```

## Installation

```bash
# Install client
sudo python3 install_client.py

# Set API key (required)
echo 'YOUR_API_KEY' | sudo tee /etc/dcmon/api_key > /dev/null
sudo chmod 600 /etc/dcmon/api_key

# Start service
sudo systemctl start dcmon-client
```

## Usage

```bash
# Check status
sudo systemctl status dcmon-client

# View logs
sudo journalctl -u dcmon-client -f

# Test collection locally
python3 test_client.py
```

## Requirements

- Python 3.7+
- aiohttp
- Root privileges (for IPMI, NVMe)
- Optional: ipmitool, nvme-cli, nvidia-smi

## Data Format

Each metric is sent as:
```json
{
  "machine_id": "unique-machine-identifier",
  "timestamp": 1693401234,
  "metrics": [
    {
      "name": "cpu_load_1m",
      "value": 2.5,
      "labels": {},
      "timestamp": 1693401234
    }
  ]
}
```

The client automatically handles:
- ✅ Integer timestamps (second precision)
- ✅ Secure API key authentication  
- ✅ Automatic retries on failure
- ✅ Graceful handling of missing exporters
- ✅ Rate limiting and error handling