# dcmon Project Reference

**System**: Production datacenter monitoring with RSA authentication, HTTPS transport, and professional dashboard  
**Architecture**: FastAPI server + SQLite, up to 100 clients, 30s metrics, Google Cloud free tier optimized

## Core Technical Decisions

**Authentication (SSH-like):**
- RSA key pairs + signature verification (PKCS1v15 + SHA256)
- Admin-controlled registration, zero public endpoints
- Basic Auth for admin operations (username: "admin", password: admin_token)
- Test mode auto-registration with dev_admin_token_12345
- Production mode prompts for secure admin token

**Database (Peewee ORM):**
- Models: Client, MetricSeries, MetricPoints{Int,Float}, Command
- Integer storage optimization (20-30% reduction)
- 7-day retention with automatic cleanup

**Transport (HTTPS):**
- Auto-generated certificates with IP SAN
- Self-signed with auto-trust (no CA dependencies)
- Preserves RSA authentication layer

**Configuration (YAML + Pydantic):**
- Unified auth_dir for all security files
- test_mode enables auto-registration with known dev token
- CLI args only override when explicitly provided (preserves config values)
- Consistent client/server config patterns

## Current Architecture

**File Structure:**
```
client/
├── client.py          # Main client (stdlib only, YAML config)
├── auth.py           # RSA authentication
├── exporters.py      # Metrics collection (OS, IPMI, GPU, NVMe, PSU)
├── fans.py           # Supermicro IPMI fan control
├── uninstall.py      # Client uninstaller script
├── install.sh        # Client installation script
├── uninstall.sh      # Client uninstallation script
└── config*.yaml      # Configuration files (production + test)

server/
├── main.py           # Entry point only (58 lines)
├── models.py         # Peewee ORM models
├── auth.py          # Authentication service
├── install.sh        # Server installation script
├── uninstall.sh      # Server uninstallation script
├── config*.yaml      # Configuration files (production + test)
├── dcmon.db          # SQLite database (generated)
├── audit.log         # Security audit log (generated)
├── core/
│   ├── config.py     # Configuration management
│   ├── server.py     # FastAPI app factory & lifespan
│   └── audit.py      # Security audit logging system
├── api/
│   ├── dependencies.py         # Auth dependencies
│   ├── schemas.py              # Pydantic models
│   ├── metric_queries.py       # Centralized metric querying
│   └── routes/
│       ├── auth_routes.py      # Registration & verification
│       ├── admin_routes.py     # Client management
│       ├── command_routes.py   # Remote commands
│       ├── metrics_routes.py   # Metrics & timeseries (pandas)
│       └── dashboard_routes.py # Web UI (htmx integration)
├── web/
│   └── template_helpers.py     # Jinja2 filters & time formatting utils
├── certificates/
│   └── certificate_manager.py # SSL/TLS handling
├── ui/               # Component-based frontend with fail-fast architecture
│   ├── components/   # Modular UI components
│   │   ├── charts/   # Chart system (chart_manager.js, timeseries_chart.js, styles)
│   │   ├── controls/ # Dashboard controls (auto-refresh, time ranges, JS + CSS)
│   │   └── tables/   # Data tables (clients_table.html/.js, HTMX integration)
│   ├── pages/        # Main templates (dashboard.html, base.html)  
│   ├── scripts/      # Utilities (ApiClient class)
│   └── styles/       # Design system (variables.css, dark mode)
├── static/           # Static asset serving
│   ├── js/           # JavaScript files
│   └── css/          # CSS stylesheets
└── dashboard/        # Dashboard logic
    ├── controller.py # Data processing with centralized operations
    └── config.py     # Metric thresholds
```

**Key APIs:**
- `POST /api/clients/register` - RSA key registration
- `POST /api/metrics` - Metric submission
- `GET /api/commands/{client_id}` - Command polling
- `POST /api/commands` - Admin command creation  
- `POST /api/command-results` - Command result submission
- `GET /api/timeseries/{metric_name}` - Time series data (optimized format)
- `GET /dashboard` - Web dashboard with smart caching
- `GET /dashboard/refresh/clients` - HTMX table refresh endpoint
- `GET /health` - Health check endpoint (admin auth required)

**Fan Control (Supermicro H11/H12/X11/X12):**
- IPMI commands: `0x30 0x45` (BMC mode), `0x30 0x70 0x66` (zone speeds)
- Remote control via command queue system
- Standard/Full Speed/Optimal/Heavy I/O modes

**PSU Monitoring (Supermicro ipmicfg):**
- Metrics: Input/output power (watts), temperatures, fan RPMs, status codes
- Command: `ipmicfg -pminfo` (requires root privileges and Supermicro hardware)
- Parsing: "[Module 1]" → "PSU1" labels, temperature format "25C/77F" → 25°C
- Enhanced availability check: `ipmicfg -ver` + `ipmicfg -pminfo` to verify actual PSU presence
- Intelligent detection: Disables exporter if no PSU modules detected (prevents constant errors)
- Raw storage: 7 integer metrics per PSU (psu_input_power_watts, psu_output_power_watts, psu_temp1_celsius, psu_temp2_celsius, psu_fan1_rpm, psu_fan2_rpm, psu_status)  
- Status mapping: OK=0, Warning=1, Critical=2, Unknown=3

**Metrics Collection (~57 metrics/client):**
- OS: CPU, RAM, disk, network (stdlib /proc parsing)
- IPMI: Temperature, fan RPM, power sensors (requires root)
- GPU: NVIDIA temp, power, utilization via nvidia-smi
- APT: Package updates, reboot status
- NVMe: Drive health, wear percentage
- PSU: Power consumption, temperature, fan RPM, status (ipmicfg -pminfo, Supermicro only)

## Metrics Query Architecture (Centralized)

**Core System (`server/api/metric_queries.py`):**
- `MetricQueryBuilder` class - single source of truth for all metric queries
- Label filtering with exact key-value matching: `[{"sensor": "CPU Temp"}, {"sensor": "VRM Temp"}]`
- Optional aggregation support: `aggregation="max|min|avg"` or `None` for latest timestamp
- Pandas vectorized operations (57.6x faster than iterrows)
- Zero parameter mapping between dashboard config and query functions

**Core Methods:**
- `MetricQueryBuilder.get_latest_metric_value(client_id, metric_name, label_filters, aggregation)`
- `MetricQueryBuilder.get_timeseries_data()` - full timeseries with aggregation
- `MetricQueryBuilder.filter_series_by_labels()` - efficient label filtering

## Dashboard Architecture (Operation-Based Metrics)

**Smart Table Configuration (`dashboard/controller.py`):**
```python
TABLE_COLUMNS = [
    # Regular metrics - direct MetricQueryBuilder mapping
    {
        "metric_name": "ipmi_temp_celsius",
        "label_filters": [{"sensor": "CPU Temp"}, {"sensor": "TEMP_CPU"}], 
        "aggregation": "max",
        "header": "CPU°C", "unit": "°", "css_class": "col-cpu-temp"
    },
    
    # Operation-based metrics - calculated values
    {
        "operation": "fraction",
        "metric_name": "disk_usage_percent",  # For threshold lookup
        "numerator": {"metric_name": "fs_used_bytes", "label_filters": [{"mountpoint": "/"}]},
        "denominator": {"metric_name": "fs_total_bytes", "label_filters": [{"mountpoint": "/"}]},
        "multiply_by": 100,
        "header": "Root%", "unit": "%", "css_class": "col-disk-root"
    }
]
```

**Operation System:**
- **Fraction operations**: `(numerator / denominator) * multiplier` for percentage calculations
- **Rate operations**: `derivative(metric[time_window])` for rates of change
- **Sum over time**: `sum(metric[time_range])` for cumulative values
- **Centralized dispatch**: `get_latest_metric()` routes to operation handlers
- **Threshold integration**: Operations use `metric_name` field for threshold lookup

**Data Processing:**
- `DashboardController.get_latest_metric()` - unified entry point for all metrics
- Operation dispatch: fraction → `_calculate_fraction()`, rate → `_calculate_rate()`
- Regular metrics → direct `MetricQueryBuilder` pass-through
- **No legacy code**: All individual metric functions removed for centralized approach

**Component Architecture**: 
- Modular HTML/CSS/JS components with HTMX integration
- Professional design system with CSS variables, dark mode support
- Chart system: ChartManager singleton with persistent cache + TimeSeriesChart factory
- Smart caching: Incremental queries (~3 records) vs full queries (~60k records)
- Layout: Header (Total, Online, Time range, Refresh) + Critical Health table

**Security & Audit:**
- Centralized audit logging system (`core/audit.py`) for authentication attempts
- Structured JSON audit logs written to `audit.log` 
- Failed authentication attempts logged with client token prefixes
- Admin authentication tracking for security monitoring

**Error Handling:**
- Stack traces enabled with `exc_info=True` for debugging
- Fail-fast architecture with clear error messages
- No defensive programming - explicit error propagation
- Clean client startup logging (reduced debug verbosity, essential INFO only)

## Installation & Operations

**Installation:**
- Server: `sudo bash install.sh` (creates dcmon-server user, systemd service, SSL certs)
- Client: `sudo bash install.sh` (auto-registration with admin token prompt)  
- Uninstallation: `sudo bash uninstall.sh` or `sudo python3 uninstall.py` (client)
- Idempotent with smart state detection (0=operational, 1=needs registration, 2=fresh install)

**Configuration:**
- Server: `/etc/dcmon-server/config.yaml` (+ `config_test.yaml` for dev)
- Client: `/etc/dcmon/config.yaml` (+ `config_test.yaml` for dev)  
- Security files in auth_dir: admin_token, server.{crt,key}, client_token
- Generated files: dcmon.db (SQLite), audit.log (security events)

**Operations:**
- Services: `systemctl {start|stop|status} dcmon-{server|client}`
- Health check: `GET /health` (admin auth required)
- Verification: `curl -u admin:dev_admin_token_12345 https://server:8000/api/clients`
- **Client Registration**: 
  - Test mode: `python3 client.py -c config_test.yaml` (auto-uses dev token)
  - Production: `python3 client.py` (prompts for admin token)
- **Admin Authentication**: Basic Auth with username "admin" and admin_token as password
- **Test Mode**: Server `python3 main.py -c config_test.yaml`, Client auto-registration

**Performance & Architecture:**
- **Network**: 87% compression (5.6KB → 0.7KB)
- **Storage**: Integer optimization for counters/bytes
- **Scale**: 100 clients on Google Cloud free tier
- **Frontend**: uPlot.js charts, HTMX partial updates, ChartManager singleton
- **Backend**: Pandas vectorized operations, centralized metric queries
- **Data Pipeline**: Backend simple format, frontend uPlot conversion (88% faster)
- **Query Strategy**: Initial load (full 24h), auto-refresh (incremental), manual refresh (force full)
- **Architecture**: Fail-fast design, operation-based metrics, centralized processing