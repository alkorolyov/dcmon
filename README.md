# dcmon Project Reference

**System**: Production datacenter monitoring with RSA authentication, HTTPS transport, and professional dashboard  
**Architecture**: FastAPI server + SQLite, up to 100 clients, 30s metrics, Google Cloud free tier optimized

## Design Principles

**Raw Data Architecture:**
- dcmon stores unprocessed sensor/log data in database
- No data transformation at collection/storage layer  
- Analysis, thresholds, alerts handled by external tools
- Data pipeline: Clients collect raw → Server stores raw → Processing tools consume raw

**Fail-Fast Philosophy:**
- Explicit error propagation instead of defensive programming
- No protective fallbacks - code fails immediately when preconditions aren't met
- Clean failures preferred over corrupted/partial data
- Clear error messages with full stack traces for debugging

**Simplicity & Performance:**
- Minimal dependencies (stdlib-focused client, FastAPI server)
- Component-based UI with single source of truth for dimensions
- Zero public endpoints - admin-controlled registration only

**Production-First Operations:**
- Self-contained deployment (no external dependencies)
- Auto-generated SSL certificates with IP SAN support
- Configurable retention and cleanup policies
- Admin-controlled client registration for security
- Google Cloud free tier optimized (up to 100 clients)

**UTC Timestamp Architecture:**
- All timestamps stored as UTC unix seconds in database and APIs
- Backend/storage layer uses only UTC (time.time(), database fields)
- Frontend converts UTC to user's local timezone for display only
- Ensures consistency across distributed clients in different timezones
- Follows industry best practices (AWS, Google Cloud, enterprise monitoring)

**Frontend Component Design:**
- **Feature-per-Directory**: Each UI component self-contained in `ui/components/[feature]/`
- **Co-location**: HTML templates, JavaScript, and CSS files together per component
- **Hierarchical Modals**: Scalable `modals/[modal_name]/` structure for future expansion
- **Consistent Naming**: `[feature]_[type].[ext]` pattern (e.g., `chart_manager.js`, `table_styles.css`)
- **Global State Management**: ChartManager singleton for cross-chart color consistency
- **No Framework Dependencies**: Vanilla JavaScript + HTMX for lightweight, maintainable code

## Core Technical Decisions

**Authentication (SSH-like):**
- RSA key pairs + signature verification (PKCS1v15 + SHA256)
- Admin-controlled registration, zero public endpoints
- Basic Auth for admin operations (username: "admin", password: admin_token)
- Test mode auto-registration with dev_admin_token_12345
- Production mode prompts for secure admin token

**Database (Peewee ORM):**
- Models: Client, MetricSeries, MetricPoints{Int,Float}, Command, LogEntry
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
├── ui/               # Component-based frontend with hierarchical organization
│   ├── components/   # Self-contained UI components (feature-per-directory)
│   │   ├── charts/   # Chart system with color consistency
│   │   │   ├── chart_manager.js      # Singleton with global client color mapping
│   │   │   ├── timeseries_chart.js   # Individual chart factory
│   │   │   ├── chart_container.html  # Chart HTML template  
│   │   │   └── chart_styles.css      # Chart-specific styles
│   │   ├── controls/ # Dashboard controls (time ranges, auto-refresh)
│   │   │   ├── dashboard_controls.js # Control logic
│   │   │   └── control_styles.css    # Control styling
│   │   ├── logs/     # Log viewing components
│   │   │   └── log_entries.html      # Log display template
│   │   ├── modals/   # Modal components (hierarchical structure)
│   │   │   └── client_detail/        # Client detail modal (self-contained)
│   │   │       ├── modal.html        # Main modal template
│   │   │       ├── modal.js          # Modal behavior & interactions
│   │   │       ├── info_tab.html     # Client information tab
│   │   │       ├── logs_tab.html     # Client logs tab
│   │   │       └── commands_tab.html # Remote commands tab
│   │   └── tables/   # Data table components
│   │       ├── clients_table.html    # Main clients table template
│   │       ├── clients_table.js      # Table logic & HTMX integration
│   │       └── table_styles.css      # Table styling
│   ├── pages/        # Main page templates (dashboard.html, base.html)  
│   ├── scripts/      # Shared utilities (ApiClient class)
│   └── styles/       # Global design system (variables.css, dark mode)
├── static/           # Static asset serving (FastAPI StaticFiles mount)
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
- `GET /api/timeseries/{metric_name}` - Time series data with JSON label filters
- `GET /api/timeseries/{metric_name}/rate` - Rate calculations for counter metrics
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

**Log Collection (Incremental + Context):**
- **dmesg**: Kernel ring buffer messages with severity filtering
- **journal**: Systemd journal with context formatting: `[unit] identifier[pid]: message`
- **syslog**: Traditional syslog file tracking with log rotation detection
- **First-run history**: Extended collection (1000 entries per source) for troubleshooting context
- **Incremental streaming**: Only new entries since last cursor position (30s polling)
- **Cursor persistence**: Stored in `{auth_dir}/log-cursors.json` for position tracking
- **Raw data storage**: Enhanced content with context, no processing beyond formatting
- **Fail-fast collection**: No fallbacks - collection failures propagate as errors
- **UTC timestamps**: All log timestamps converted to UTC unix seconds for consistency across timezones
  - dmesg: boot_time (UTC from /proc/stat) + kernel_seconds
  - journal: __REALTIME_TIMESTAMP (UTC microseconds from systemd) 
  - syslog: Local timestamp parsed and converted to UTC

## Metrics Query Architecture (Centralized)

**Core System (`server/api/metric_queries.py`):**
- `MetricQueryBuilder` class - single source of truth for all metric queries
- **Centralized sensor mappings**: `CPU_SENSORS = [{"sensor": "CPU Temp"}, {"sensor": "TEMP_CPU"}]` for multi-motherboard support
- **VRM sensor mappings**: `VRM_SENSORS = [{"sensor": "CPU_VRM Temp"}, {"sensor": "SOC_VRM Temp"}, ...]` for different VRM types
- Label filtering with exact key-value matching using centralized constants
- Optional aggregation support: `aggregation="max|min|avg"` or `None` for latest timestamp
- **Vectorized pandas operations**: `.to_dict('records')` and `.groupby()` instead of slow `iterrows()`
- Zero parameter mapping between dashboard config and query functions

**Core Methods:**
- `MetricQueryBuilder.get_latest_metric_value(client_id, metric_name, label_filters, aggregation)`
- `MetricQueryBuilder.get_timeseries_data()` - full timeseries with aggregation
- `MetricQueryBuilder.get_rate_timeseries()` - rate calculations for counter metrics
- `MetricQueryBuilder.filter_series_by_labels()` - efficient label filtering

## Dashboard Architecture (Operation-Based Metrics)

**Smart Table Configuration (`dashboard/controller.py`):**
```python
# Import centralized sensor mappings from metric_queries
from ..api.metric_queries import MetricQueryBuilder, CPU_SENSORS, VRM_SENSORS

TABLE_COLUMNS = [
    # Regular metrics using centralized sensor mappings
    {
        "metric_name": "ipmi_temp_celsius",
        "label_filters": CPU_SENSORS,  # [{"sensor": "CPU Temp"}, {"sensor": "TEMP_CPU"}]
        "aggregation": "max",
        "header": "CPU°C", "unit": "°", "css_class": "col-cpu-temp"
    },
    {
        "metric_name": "ipmi_temp_celsius", 
        "label_filters": VRM_SENSORS,  # Multi-VRM sensor support
        "aggregation": "max",
        "header": "VRM°C", "unit": "°", "css_class": "col-vrm-temp"
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

**Component-Based Frontend Architecture**: 
- **Self-Contained Components**: Each feature organized in its own directory (`ui/components/[feature]/`)
- **Co-Located Assets**: HTML templates, JavaScript, and CSS together per component
- **Hierarchical Modals**: Scalable modal structure (`modals/client_detail/`, `modals/metric_config/`)
- **Color Consistency**: Global client color mapping across all charts via ChartManager singleton
- **Smart Chart System**: Persistent cache, incremental updates, synchronized zoom/pan
- **HTMX Integration**: Partial page updates with component-based templates
- **Design System**: CSS variables, dark mode support, consistent naming (`[feature]_[type].[ext]`)
- **Future-Ready**: Easy to add new features following established component patterns

**Security & Audit:**
- Centralized audit logging system (`core/audit.py`) for authentication attempts
- Structured JSON audit logs written to `audit.log` 
- Failed authentication attempts logged with client token prefixes
- Admin authentication tracking for security monitoring

**Implementation Details:**
- **Error Handling**: Stack traces enabled with `exc_info=True` for debugging
- **Precondition Checks**: Valid checks (e.g., `if (!this.chartManager) throw new Error()`) but no fallback defaults
- **Explicit Dependencies**: Components assume required dependencies exist rather than checking and falling back
- **Client Logging**: Clean startup logging (reduced debug verbosity, essential INFO only)
- **Clean Code Standards**: All imports at top of files, no backward compatibility, vectorized pandas operations
- **Centralized Constants**: Sensor mappings in single source of truth prevent code duplication across components
- **UI Constants**: JavaScript constants as authoritative source for programmatic UI components  
- **CSS Integration**: Custom properties generated from JS constants for styling consistency
- **Chart Color Consistency**: Global client hostname → color mapping ensures same client has same color across all charts
- **Component Pattern**: `const UI_CONSTANTS = { CHART_HEIGHT: 200 }; document.documentElement.style.setProperty('--chart-height', UI_CONSTANTS.CHART_HEIGHT + 'px');`

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
- **Time Range Performance**: Cached data filtering with axis rescaling (no database queries on range changes)
- **API Design**: Integer seconds parameter (300s-7776000s) instead of fractional hours for precision
- **Architecture**: Fail-fast design, operation-based metrics, centralized processing