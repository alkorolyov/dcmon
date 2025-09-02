# dcmon Development Archive (Compressed)

**System**: Production datacenter monitoring with RSA authentication, HTTPS transport, and professional dashboard
**Architecture**: FastAPI server + SQLite, up to 100 clients, 30s metrics, Google Cloud free tier optimized

## Core Technical Decisions

**Authentication V2 (SSH-like):**
- RSA key pairs + signature verification (PKCS1v15 + SHA256)
- Admin-controlled registration, zero public endpoints
- One-time admin token use, clients never store admin credentials

**Database V2 (Peewee ORM):**
- Migrated from 200+ lines custom SQL to ORM
- Models: Client, MetricSeries, MetricPoints{Int,Float}, Command
- Integer storage optimization (20-30% reduction)
- 7-day retention with automatic cleanup

**Transport V2 (HTTPS):**
- Auto-generated certificates with IP SAN
- Self-signed with auto-trust (no CA dependencies)
- Preserves RSA authentication layer

**Configuration (YAML + Dataclass):**
- Unified auth_dir for all security files
- test_mode controls admin token fallback
- Consistent client/server config patterns

## Implementation Architecture

**File Structure:**
```
client/
├── client.py          # Main client (stdlib only, YAML config)
├── auth.py           # RSA authentication
├── exporters.py      # Metrics collection
└── fans.py           # Supermicro IPMI fan control

server/
├── main.py           # FastAPI app factory
├── routes.py         # API routes (separated)
├── models.py         # Peewee ORM models
├── auth.py          # Authentication service
└── dashboard/        # Web dashboard
    ├── controller.py # Dashboard data logic
    ├── config.py    # Metric thresholds
    └── templates/   # Jinja2 templates
```

**Key APIs:**
- `POST /api/register` - RSA key registration
- `POST /api/metrics` - Metric submission
- `GET /api/commands/{machine_id}` - Command polling
- `POST /api/commands` - Admin command creation
- `GET /api/client/verify` - Registration validation

**Fan Control (Supermicro H11/H12/X11/X12):**
- IPMI commands: `0x30 0x45` (BMC mode), `0x30 0x70 0x66` (zone speeds)
- Remote control via command queue system
- Standard/Full Speed/Optimal/Heavy I/O modes

**Installation System:**
- Shell script installers (no Python dependency)
- Idempotent with smart state detection (0=operational, 1=needs registration, 2=fresh install)
- Auto-generates RSA keys and HTTPS certificates
- Interactive admin token prompting with validation
- Complete uninstall scripts

**Metrics Collection (~50 metrics/client):**
- OS: CPU, RAM, disk, network (stdlib /proc parsing)
- IPMI: Temperature, fan RPM, power sensors (requires root)
- GPU: NVIDIA temp, power, utilization via nvidia-smi
- APT: Package updates, reboot status
- NVMe: Drive health, wear percentage

**Database Models (Peewee ORM):**
```python
class Client(Model):
    hostname, machine_id, client_token, last_seen
    
class MetricSeries(Model):
    client, metric_name, labels (JSON)
    
class MetricPoints{Int,Float}(Model):
    series, timestamp, value
    
class Command(Model):
    machine_id, command_type, command_data, status, result
```

**Command System:**
- Polling architecture (clients check every ~90s)
- Commands: fan_control, reboot, config_update
- JSON payloads with status tracking
- Server-initiated, client-executed


**Deployment:**
- Server: `sudo bash install.sh` (creates dcmon-server user, systemd service)
- Client: `sudo bash install.sh` (auto-registration with admin token prompt)
- Verification: `curl https://server:8000/api/clients` with admin token

**Performance:**
- Network: 5.6KB → 0.7KB (87% compression)
- Storage: Integer optimization for counters/bytes
- Retention: 7 days automatic cleanup
- Scale: 100 clients on Google Cloud free tier



**Operations:**
- Services: `systemctl {start|stop|status} dcmon-{server|client}`
- Config: `/etc/dcmon-server/config.yaml`, `/etc/dcmon/config.yaml`
- Security files in auth_dir: admin_token, server.{crt,key}, client_token
- Health check: `GET /health` (admin auth required)


## V2.0-2.1: Authentication & Installation

**V2.0 Core System:**
- RSA authentication (SSH-like key pairs)
- Peewee ORM migration (90% code reduction)
- YAML configuration with dataclass validation
- Modern FastAPI with lifespan handlers
- Zero public endpoints, admin-controlled registration

**V2.1 Installation:**
- Interactive client registration with admin token prompting
- Idempotent installation with smart state detection
- YAML config migration (client + server)
- Dependency-free client (stdlib only)
- Route separation (main.py + routes.py)
- End-to-end test suite with ephemeral admin tokens


## V2.2: Advanced Hardware Integration

**BMC Fan Control:**
- BMCFanExporter with Supermicro H11/H12/X11/X12 detection
- IPMI metrics: `bmc_fan_mode`, `bmc_fan_zone_speed{zone="0|1"}`
- Hardware availability checking (single startup check per exporter)
- FanController singleton optimization

**Metrics Architecture:**
- MetricsExporter base class with `is_available()` pattern
- Hardware-specific availability: root privileges, IPMI access, hardware compatibility
- Centralized hardware data flow: client.py → exporters
- Python 3.8+ compatibility fixes (Tuple typing, cryptography backend)

**Configuration:**
- YAML field name corrections (server, auth_dir, interval)
- Exporters section support
- Zero backward compatibility

## V2.3: HTTPS Transport & Configuration

**HTTPS Implementation:**
- Self-signed certificates with IP SAN auto-generation
- Client auto-trust (no certificate distribution)
- Preserves RSA authentication layer
- Development: auto-cert generation, production: explicit certificates

**Unified Configuration:**
- auth_dir approach: all security files in single directory
- test_mode: consistent dev admin token vs required file
- Clean separation: auth_dir vs db_path
- Certificate management: install script integration with proper permissions

## V2.4: Professional Dashboard & Code Cleanup

**Grafana-Style Dashboard:**
- Single row header: Total, Online (green), Time range, Refresh, Refresh interval
- Eliminated 25% wasted vertical space (removed excessive padding)
- Professional styling: removed all emojis, unified CSS system
- Single Critical Health table (11 columns): Status, Machine, CPU°C, CPU%, VRM°C, GPU°C, GPU Power, GPU Limit, GPU Fan%, RAM%, Root%, Docker%
- Color-coded metrics: Blue → Green → Yellow → Red based on thresholds

**Code Cleanup:**
- Template cleanup: removed old files (clients_table_old.html, client_grid.html, metric_table.html)
- Controller simplification: eliminated 15+ unused methods (500+ lines removed)
- Configuration cleanup: removed old table configurations and backward compatibility
- CSS unification: single dashboard.css with Grafana colors and Inter typography

**Architecture:**
- 90% reduction in template complexity
- Zero technical debt or unused code paths
- Professional color scheme with CSS variables
- Responsive design with proper breakpoints