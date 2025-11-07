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
python3 client/client.py

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

Current test coverage: 26 passing tests covering:
- Label filtering
- Latest metric value retrieval
- Raw time-series queries
- Time-series aggregation
- Rate calculation (with large counter values)

### Project Structure

```
dcmon/
├── server/
│   ├── api/                    # API routes and schemas
│   ├── core/                   # Core application logic
│   ├── dashboard/              # Dashboard controller
│   ├── certificates/           # Client certificates
│   ├── migrations/             # Database migrations
│   ├── ui/                     # Frontend templates and assets
│   └── models.py               # Database models
├── client/
│   ├── exporters/              # Metric exporters
│   │   └── metrics/           # Individual metric collectors
│   ├── client.py              # Main client application
│   └── config.yaml            # Client configuration
└── tests/
    └── unit/                   # Unit tests
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

## Recent Updates

### Major Refactor (November 2025)
- Migrated to float-only metric storage
- Fixed rate calculation for multi-metric aggregation
- Added number formatting with K/M/G/T abbreviations
- Improved chart visibility for flat lines
- Added comprehensive test coverage
- Fixed client log display issues

## Contributing

This project follows a refactored, AI-friendly architecture with:
- Clear separation of concerns
- Centralized query logic
- Comprehensive error handling
- Detailed commit messages
- Test coverage for critical paths

## License

[Your License Here]

## Support

For issues, questions, or contributions, please open an issue on the repository.
