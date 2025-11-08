# dcmon - Datacenter Monitoring System

A lightweight, self-hosted monitoring solution for datacenter infrastructure with real-time metrics collection, alerting, and web dashboard.

## Features

- **Real-time Metrics Collection**
  - System metrics: CPU, memory, disk, network
  - Hardware monitoring: IPMI temperatures, fan speeds, PSU stats
  - GPU monitoring: NVIDIA GPU temperature, utilization, power, fan speed
  - Docker container metrics
  - Custom script-based metrics

- **Web Dashboard**
  - Interactive charts with time range selection
  - Client status overview with online/offline filtering
  - Real-time updates via HTMX
  - Client detail modals with logs and hardware info
  - Grafana-style time-series visualization

- **Log Collection**
  - System logs: journal, syslog, dmesg
  - Application-specific logs (e.g., vast.ai)
  - 7-day retention (configurable)

- **Remote Command Execution**
  - WebSocket-based real-time commands
  - Fan control (IPMI-based)
  - System information queries
  - Raw IPMI command execution

- **Data Retention & Cleanup**
  - Automatic cleanup of old metrics (30 days default)
  - Automatic cleanup of old logs (7 days default)
  - Configurable retention periods

## Architecture

### Server
- **FastAPI** backend with async support
- **SQLite** database for metrics and logs
- **Peewee ORM** for database access
- **HTTPS** with TLS encryption
- **Token-based authentication** for clients and admins
- **Certificate management** for client connections
- **Audit logging** for admin actions

### Client
- Python-based agent with pluggable metric exporters
- Automatic reconnection with exponential backoff
- WebSocket connection for real-time commands
- SSH tunnel support for secure connections
- Metric caching during disconnections

### Metrics Storage
- Float-only architecture for all metrics
- Separate tables for different metric types (optimized queries)
- Time-series data with efficient indexing
- Rate calculation for counter metrics (Grafana-style)

## Installation

### Server Setup

```bash
cd server
./install.sh
```

This will:
- Install system dependencies
- Create Python virtual environment
- Generate server certificates
- Create default config.yaml
- Set up systemd service (optional)

### Configuration

Edit `server/config.yaml`:

```yaml
# Server settings
host: 0.0.0.0
port: 8000
log_level: INFO

# Data retention
metrics_days: 30  # Keep metrics for 30 days
logs_days: 7      # Keep log entries for 7 days

# Authentication
admin_token_file: admin_token
client_cert_dir: certificates/clients

# TLS
tls_cert: server.crt
tls_key: server.key
```

### Client Setup

```bash
cd client
./install.sh
```

This will:
- Install dependencies
- Generate client certificate
- Register with server
- Set up systemd service (optional)

Edit `client/config.yaml` to configure which metrics to collect.

## Usage

### Starting the Server

```bash
# Development
python3 -m server.core.app

# Production (systemd)
systemctl start dcmon-server
```

Access dashboard at: `https://localhost:8000/dashboard`

Default admin credentials:
- Username: `admin`
- Token: (found in `server/admin_token`)

### Starting the Client

```bash
# Development
python3 client/main.py

# Production (systemd)
systemctl start dcmon-client
```

## API Endpoints

### Metrics
- `POST /api/metrics` - Submit metrics batch from client
- `GET /api/timeseries/{metric_name}` - Get time-series data
- `GET /api/timeseries/{metric_name}/rate` - Get rate calculations

### Dashboard
- `GET /dashboard` - Main dashboard page
- `GET /dashboard/refresh/clients` - Refresh client table (HTMX)
- `GET /dashboard/client/{id}/modal` - Client detail modal
- `GET /dashboard/client/{id}/logs/{source}` - Client logs

### Commands
- `WS /ws/client/{id}` - WebSocket for client commands
- `POST /api/commands` - Execute command on client
- `POST /api/clients/{id}/command/fan-mode` - Set fan mode
- `GET /api/clients/{id}/command/fan-status` - Get fan status

## Development

### Running Tests

```bash
pytest tests/unit/
```

Current test coverage: **135 passing tests** covering:
- Authentication (token generation, signature verification, admin/client auth)
- Dashboard controller (metrics aggregation, client status, detail views)
- Device categorization (GPU, PSU, network, storage devices)
- Metric query builder (label filtering, latest values, time-series, rates)
- Metrics ingestion (series creation, point storage, batch submission)
- Rate calculations (Grafana-style rate[5m], counter resets, large values)

### Project Structure

```
dcmon/
├── server/
│   ├── api/
│   │   ├── queries/            # Metric query modules (modular architecture)
│   │   │   ├── latest.py       # Latest value queries
│   │   │   ├── timeseries.py   # Time-series data retrieval
│   │   │   ├── rates.py        # Rate calculations
│   │   │   ├── labels.py       # Label formatting & GPU mapping
│   │   │   ├── utils.py        # Shared utilities
│   │   │   └── constants.py    # Sensor mappings
│   │   ├── routes/             # API endpoint definitions
│   │   │   ├── auth_routes.py
│   │   │   ├── metrics_routes.py
│   │   │   ├── dashboard_routes.py
│   │   │   ├── command_routes.py
│   │   │   └── admin_routes.py
│   │   ├── dependencies.py     # FastAPI dependencies
│   │   └── schemas.py          # Pydantic models
│   ├── core/                   # Core application logic
│   │   ├── config.py           # Configuration management
│   │   ├── server.py           # FastAPI app factory
│   │   └── audit.py            # Audit logging
│   ├── dashboard/              # Dashboard logic
│   │   ├── controller.py       # Data preparation
│   │   ├── config.py           # Column configuration
│   │   └── device_rules.py     # Device categorization (table-driven)
│   ├── certificates/           # SSL/TLS certificate management
│   ├── ui/                     # Frontend (vanilla JS, no framework)
│   │   ├── components/         # Reusable UI components
│   │   ├── pages/              # Page templates
│   │   ├── scripts/            # JavaScript utilities
│   │   └── styles/             # CSS stylesheets
│   ├── web/                    # Template helpers (Jinja2 filters)
│   ├── auth.py                 # Authentication service
│   └── models.py               # Database models (Peewee ORM)
├── client/
│   ├── exporters/
│   │   ├── metrics/            # Individual metric collectors
│   │   │   ├── os_metrics.py
│   │   │   ├── ipmi.py
│   │   │   ├── nvsmi.py        # NVIDIA GPU
│   │   │   ├── nvme.py
│   │   │   ├── psu.py
│   │   │   └── ...
│   │   └── logs/               # Log collection exporters
│   ├── main.py                 # Client entry point
│   ├── auth.py                 # RSA authentication
│   ├── http_client.py          # HTTP utilities (stdlib only)
│   ├── commands.py             # WebSocket command handler
│   └── config.yaml             # Client configuration
└── tests/
    └── unit/                   # Unit tests (135 tests)
```

## Rate Calculation

dcmon implements Grafana-style `rate[5m]` calculations for counter metrics:

- Looks back over a time window (default 5 minutes)
- Calculates rate from first to last value in window
- Handles counter resets gracefully
- Supports aggregation across multiple metrics

Example: Network I/O rate combines receive + transmit rates
```
rate[5m](network_receive_bytes_total + network_transmit_bytes_total)
```

## Architecture Highlights

### AI-Friendly Codebase
This project is optimized for AI-assisted development and maintainability:

**Modular Query System** (`server/api/queries/`)
- Split into focused modules (latest, timeseries, rates, labels)
- Each module under 200 lines for better comprehension
- Clear separation of concerns (one responsibility per module)
- Backwards compatible via `MetricQueryBuilder` wrapper

**Table-Driven Logic** (`server/dashboard/device_rules.py`)
- Device categorization via declarative lookup tables
- Easy to extend (add row vs. modify complex if/elif chains)
- GPU, PSU, network, storage device support

**Minimal Dependencies**
- Client: Only 3 packages (cryptography, PyYAML, websockets)
- Uses Python stdlib (`urllib`) instead of heavy HTTP libraries
- Frontend: Vanilla JavaScript (no React/Vue/build pipeline)

**Comprehensive Testing**
- 135 unit tests with >80% coverage
- Test fixtures for all major components
- Clean test organization by feature

## Contributing

This project follows a refactored, AI-friendly architecture with:
- **Clear separation of concerns** - Each module has single responsibility
- **Modular query system** - Latest, timeseries, rates, labels separated
- **Table-driven logic** - Declarative rules instead of complex conditionals
- **Comprehensive error handling** - Fail-fast with clear error messages
- **Detailed commit messages** - Full context for each change
- **Test coverage** - 135 tests covering critical paths
- **2-layer architecture** - Keep it simple (no over-abstraction)

## License

[Your License Here]

## Support

For issues, questions, or contributions, please open an issue on the repository.
