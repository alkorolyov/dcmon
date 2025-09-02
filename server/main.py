#!/usr/bin/env python3
"""
dcmon FastAPI server — config-first, path-free, policy-enforced

Policy (no paths in config):
- PROD (test_mode: false)
    DB:         /var/lib/dcmon-server/dcmon.db
    Admin token:/etc/dcmon-server/admin_token  (must exist; else startup fails)
- DEV  (test_mode: true)
    DB:         ./dcmon.db
    Admin token:./admin_token  (if missing, generate ephemeral and log)

Identity: Client.id (peewee default PK)
Credentials: client_token (client), admin_token (server-side)

This file also runs a periodic cleanup task that removes metrics older than
`metrics_days` (config) every hour.
"""

import argparse
import asyncio
import json
import time
import logging
from contextlib import asynccontextmanager
from secrets import compare_digest
from typing import Any, Dict, List, Optional

import yaml
from fastapi import FastAPI, Depends, HTTPException, status, Query, Path, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, model_validator

# Support running as script or as package
try:
    from .models import db_manager, Client, MetricSeries, MetricPointsInt, MetricPointsFloat, Command
    from .auth import AuthService
    from .dashboard import DashboardController
except ImportError:
    from models import db_manager, Client, MetricSeries, MetricPointsInt, MetricPointsFloat, Command
    from auth import AuthService
    from dashboard import DashboardController

logger = logging.getLogger("dcmon.server")


# ---------------- Config (path-free) ----------------

class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    metrics_days: int = 7
    # File paths - explicit configuration
    auth_dir: str
    db_path: str
    # Behavior controls
    test_mode: bool = False          # Only controls admin token fallback
    use_tls: bool = False           # Controls HTTPS on/off


def load_config_from(path: str) -> ServerConfig:
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    return ServerConfig(**data)


# ---------------- Path policy helpers ----------------

def _resolve_paths(cfg: ServerConfig):
    """
    Return (db_path, admin_token_path, allow_ephemeral_admin_token, cert_path, key_path)
    based on explicit config paths.
    """
    from pathlib import Path
    auth_dir = Path(cfg.auth_dir)
    
    return (
        Path(cfg.db_path),                    # Database at explicit path
        auth_dir / "admin_token",             # Admin token in auth_dir
        cfg.test_mode,                        # Only controls admin token fallback
        auth_dir / "server.crt",              # Certificate in auth_dir
        auth_dir / "server.key"               # Private key in auth_dir
    )


def _read_admin_token(path) -> Optional[str]:
    try:
        with open(path, "r") as f:
            tok = f.read().strip()
            return tok or None
    except Exception as e:
        logger.debug("admin token file not readable (%s): %s", path, e)
        return None


# ---------------- App factory ----------------

def create_app(config: ServerConfig) -> FastAPI:
    """
    Build the FastAPI app using the provided config.
    """
    security = HTTPBearer(auto_error=False)
    auth_service = AuthService()
    ADMIN_TOKEN: Optional[str] = None
    cleanup_task: Optional[asyncio.Task] = None
    
    CLEANUP_INTERVAL_SECONDS = 3600  # hourly

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal ADMIN_TOKEN, cleanup_task

        # Configure logging early
        log_level = getattr(logging, config.log_level.upper(), logging.INFO)
        logging.basicConfig(level=log_level, format='%(levelname)s:%(name)s:%(message)s')
        logging.getLogger().setLevel(log_level)
        logger.setLevel(log_level)
        
        # Silence noisy third-party loggers
        logging.getLogger('peewee').setLevel(logging.WARNING)

        # Resolve paths from policy
        db_path, admin_token_path, allow_ephemeral, cert_path, key_path = _resolve_paths(config)
        logger.info("resolved paths: db=%s, admin_token=%s, cert=%s, key=%s, test_mode=%s",
                    db_path, admin_token_path, cert_path, key_path, config.test_mode)

        # Apply DB path before connecting
        try:
            from pathlib import Path
            db_manager.db_path = Path(db_path)
        except Exception:
            pass

        if not db_manager.connect():
            logger.error("Failed to connect database on startup.")
            raise RuntimeError("DB connect failed")

        # Admin token resolution
        token = _read_admin_token(admin_token_path)
        if token is None and allow_ephemeral:
            # In test mode, use a consistent admin token for development
            token = "dev_admin_token_12345"
            logger.warning("No admin token file found; using CONSISTENT dev admin token: %s", token)
            logger.warning("To use a different token in dev, create ./admin_token with 0600 perms.")
        if token is None and not allow_ephemeral:
            db_manager.close()
            raise RuntimeError(
                f"Admin token file missing at {admin_token_path}. "
                f"Create it with a secure token generated by the installer."
            )
        ADMIN_TOKEN = token

        # Start periodic cleanup (run in executor so we don't block the event loop)
        async def _cleanup_loop():
            loop = asyncio.get_running_loop()
            while True:
                try:
                    # Cleanup both int and float points
                    deleted_int = await loop.run_in_executor(None, MetricPointsInt.cleanup_old_data, config.metrics_days)
                    deleted_float = await loop.run_in_executor(None, MetricPointsFloat.cleanup_old_data, config.metrics_days)
                    deleted_total = deleted_int + deleted_float
                    logger.debug("periodic cleanup: removed %s int points, %s float points (%s days)", 
                                deleted_int, deleted_float, config.metrics_days)
                except Exception as e:
                    logger.error("periodic cleanup failed: %s", e)
                await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

        cleanup_task = asyncio.create_task(_cleanup_loop())

        logger.info("dcmon server started (host=%s, port=%d)", config.host, config.port)
        try:
            yield
        finally:
            # Stop cleanup task
            if cleanup_task:
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass
            db_manager.close()
            logger.info("dcmon server stopped")

    app = FastAPI(title="dcmon server", version="0.1.0", lifespan=lifespan)

    # ------------- Auth dependencies -------------

    def require_admin_auth(request: Request) -> None:
        """
        Simple Basic Auth for both test and production modes.
        In test mode, use any username + dev_admin_token_12345 as password.
        In production mode, use any username + real admin token as password.
        """
        auth_header = request.headers.get("authorization", "")
        
        if auth_header.startswith("Basic "):
            import base64
            try:
                credentials = base64.b64decode(auth_header[6:]).decode('utf-8')
                if ":" in credentials:
                    username, password = credentials.split(":", 1)
                    if ADMIN_TOKEN and compare_digest(password, ADMIN_TOKEN):
                        logger.debug("Admin authenticated via Basic Auth")
                        return
            except Exception:
                pass
        
        # Authentication failed - prompt for Basic Auth
        realm_msg = "dcmon Admin (test mode: use any username + dev_admin_token_12345)" if config.test_mode else "dcmon Admin"
        logger.warning("Admin authentication failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": f"Basic realm=\"{realm_msg}\""}
        )
    

    def require_client_auth(creds: HTTPAuthorizationCredentials = Depends(security)) -> Client:
        token = creds.credentials
        client = Client.get_by_token(token)
        if not client:
            logger.warning(f"Client authentication failed with token: {token[:8]}...")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid client token")
        return client


    # ------------- Schemas (pydantic v2) -------------

    class RegistrationRequest(BaseModel):
        hostname: str
        public_key: str
        challenge: str
        signature: str
        timestamp: int
        # System identification
        machine_id: str
        hw_hash: Optional[str] = None
        # Hardware inventory fields (optional)
        mdb_name: Optional[str] = None
        cpu_name: Optional[str] = None
        gpu_name: Optional[str] = None
        gpu_count: Optional[int] = None
        ram_gb: Optional[int] = None
        cpu_cores: Optional[int] = None
        drives: Optional[List[Dict[str, Any]]] = None

    class MetricRecord(BaseModel):
        timestamp: int
        metric_name: str = Field(..., min_length=1)
        value_type: str = Field(..., pattern="^(int|float)$")
        value: float  # Accept as float, will be cast to int if value_type is "int"
        labels: Optional[Dict[str, Any]] = None

        @model_validator(mode="after")
        def _validate_value_type(self) -> "MetricRecord":
            if self.value_type == "int":
                # Validate that the value can be converted to int
                try:
                    int(self.value)
                except (ValueError, OverflowError):
                    raise ValueError(f"value {self.value} cannot be converted to integer")
            return self

    class MetricsBatchRequest(BaseModel):
        metrics: List[MetricRecord]
        hw_hash: Optional[str] = None

    class CommandResultRequest(BaseModel):
        command_id: str
        status: str = Field("completed", pattern="^(completed|failed)$")
        result: Optional[Dict[str, Any]] = None

    # ------------- Routes -------------

    @app.post("/api/clients/register", status_code=201, dependencies=[Depends(require_admin_auth)])
    def register_client(request: RegistrationRequest):
        vr = auth_service.validate_registration_request(request.model_dump())
        if not vr.get("valid"):
            raise HTTPException(status_code=422, detail=vr.get("error") or "invalid request")

        # Check if client with this machine_id already exists
        existing_client = Client.get_by_machine_id(request.machine_id)
        if existing_client:
            # Update last_seen and return existing client
            existing_client.update_last_seen()
            logger.info(f"EXISTING CLIENT: {request.hostname} (machine_id: {request.machine_id[:8]}...) - returned existing client_id: {existing_client.id}")
            return {
                "client_id": existing_client.id, 
                "client_token": existing_client.client_token,
                "message": "Client already registered, using existing token"
            }

        client_token = auth_service.generate_client_token()
        client_id = db_manager.register_client(
            hostname=vr["hostname"],
            client_token=client_token,
            machine_id=request.machine_id,
            hw_hash=request.hw_hash,
            public_key=vr["public_key"],
            # Hardware inventory
            mdb_name=request.mdb_name,
            cpu_name=request.cpu_name,
            gpu_name=request.gpu_name,
            gpu_count=request.gpu_count,
            ram_gb=request.ram_gb,
            cpu_cores=request.cpu_cores,
            drives=request.drives,
        )
        if client_id is None:
            raise HTTPException(status_code=500, detail="failed to register client")

        logger.info(f"NEW CLIENT: {request.hostname} (machine_id: {request.machine_id[:8]}...) - client_id: {client_id}")
        
        return {"client_id": client_id, "client_token": client_token}

    @app.post("/api/metrics")
    def submit_metrics(body: MetricsBatchRequest, client: Client = Depends(require_client_auth)):
        now = int(time.time())
        int_points = []
        float_points = []
        
        for m in body.metrics:
            if m.timestamp > now + 300:
                raise HTTPException(status_code=422, detail=f"metric timestamp too far in future: {m.timestamp}")
            
            # Get or create metric series
            labels_json = json.dumps(m.labels) if m.labels else None
            series = MetricSeries.get_or_create_series(
                client_id=client.id,
                metric_name=m.metric_name, 
                labels=labels_json,
                value_type=m.value_type
            )
            
            # Prepare data for appropriate points table
            if m.value_type == "int":
                int_points.append({
                    "series": series.id,
                    "timestamp": m.timestamp,
                    "value": int(m.value)
                })
            else:  # float
                float_points.append({
                    "series": series.id,
                    "timestamp": m.timestamp,
                    "value": m.value
                })
        
        # Bulk insert points
        inserted_total = 0
        if int_points:
            inserted_int = MetricPointsInt.insert_many(int_points).on_conflict_ignore().execute()
            inserted_total += int(inserted_int or 0)
            
        if float_points:
            inserted_float = MetricPointsFloat.insert_many(float_points).on_conflict_ignore().execute()
            inserted_total += int(inserted_float or 0)

        # Hardware change detection
        if body.hw_hash and body.hw_hash != client.hw_hash:
            logger.warning(f"Hardware changed on client {client.id} ({client.hostname})")
            # TODO: Request full hardware details and compare
            # For now, just update the stored hash
            client.hw_hash = body.hw_hash
            client.save()
        
        client.update_last_seen()
        logger.debug(f"Metrics from client {client.id} ({client.hostname}): received {len(body.metrics)}, inserted {inserted_total}")
        return {"received": len(body.metrics), "inserted": inserted_total}

    @app.get("/api/commands/{client_id}")
    def get_client_commands(
        client_id: int = Path(..., ge=1),
        client: Client = Depends(require_client_auth),
    ):
        if client.id != client_id:
            raise HTTPException(status_code=403, detail="token does not belong to requested client_id")

        cmds = Command.get_pending_for_client(client_id)
        out = []
        for c in cmds:
            try:
                data = json.loads(c.command_data)
            except Exception:
                data = c.command_data
            out.append({
                "id": c.id,
                "client_id": client_id,
                "command_type": c.command_type,
                "command_data": data,
                "status": c.status,
                "created_at": c.created_at,
            })
        return {"commands": out}

    @app.post("/api/command-results")
    def submit_command_result(body: CommandResultRequest, client: Client = Depends(require_client_auth)):
        try:
            cmd = Command.get_by_id(body.command_id)
        except Command.DoesNotExist:
            raise HTTPException(status_code=404, detail="command not found")

        if (isinstance(cmd.client, Client) and cmd.client.id != client.id) or \
           (not isinstance(cmd.client, Client) and int(cmd.client) != client.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="command not owned by this client")

        if body.status == "completed":
            cmd.mark_completed(result=body.result or {})
        else:
            err = ""
            if body.result and "error" in body.result:
                err = str(body.result["error"])
            elif body.result is not None:
                err = json.dumps(body.result)
            else:
                err = "unknown error"
            cmd.mark_failed(error=err)

        return {"ok": True}

    @app.get("/api/clients", dependencies=[Depends(require_admin_auth)])
    def list_clients():
        items = []
        for c in Client.select().order_by(Client.last_seen.desc(nulls="LAST")):
            items.append(c.to_dict())
        return {"clients": items}

    @app.get("/api/metrics", dependencies=[Depends(require_admin_auth)])
    def query_metrics(
        client_id: Optional[int] = Query(None, ge=1),
        metric_name: Optional[List[str]] = Query(None),
        start: Optional[int] = Query(None),
        end: Optional[int] = Query(None),
        limit: int = Query(1000, ge=1, le=10000),
    ):
        # Build query for metric series
        series_query = MetricSeries.select()
        if client_id:
            series_query = series_query.where(MetricSeries.client == client_id)
        if metric_name:
            series_query = series_query.where(MetricSeries.metric_name.in_(metric_name))
        
        series_list = list(series_query)
        if not series_list:
            return {"metrics": []}
        
        series_ids = [s.id for s in series_list]
        out = []
        
        # Query float points
        float_query = MetricPointsFloat.select().where(MetricPointsFloat.series.in_(series_ids))
        if start:
            float_query = float_query.where(MetricPointsFloat.timestamp >= start)
        if end:
            float_query = float_query.where(MetricPointsFloat.timestamp <= end)
        float_query = float_query.order_by(MetricPointsFloat.timestamp.desc()).limit(limit // 2)
        
        for point in float_query:
            series = next(s for s in series_list if s.id == point.series.id)
            out.append({
                "client_id": series.client.id,
                "timestamp": point.timestamp,
                "metric_name": series.metric_name,
                "value_float": point.value,
                "value_int": None,
                "labels": json.loads(series.labels) if series.labels else None,
            })
        
        # Query int points
        int_query = MetricPointsInt.select().where(MetricPointsInt.series.in_(series_ids))
        if start:
            int_query = int_query.where(MetricPointsInt.timestamp >= start)
        if end:
            int_query = int_query.where(MetricPointsInt.timestamp <= end)
        int_query = int_query.order_by(MetricPointsInt.timestamp.desc()).limit(limit // 2)
        
        for point in int_query:
            series = next(s for s in series_list if s.id == point.series.id)
            out.append({
                "client_id": series.client.id,
                "timestamp": point.timestamp,
                "metric_name": series.metric_name,
                "value_float": None,
                "value_int": point.value,
                "labels": json.loads(series.labels) if series.labels else None,
            })
        
        # Sort by timestamp descending
        out.sort(key=lambda x: x["timestamp"], reverse=True)
        return {"metrics": out[:limit]}

    @app.get("/api/timeseries/{metric_name}")
    def get_timeseries(
        metric_name: str,
        hours: int = Query(24, ge=1, le=168),  # 1 hour to 1 week
        clients: Optional[List[int]] = Query(None),
        aggregation: str = Query("max", pattern="^(max|min|avg|sum|raw)$"),
        admin_auth: bool = Depends(require_admin_auth)  # Uses Basic Auth like dashboard
    ):
        """
        General-purpose timeseries endpoint for dashboard charts.
        Uses Basic Auth authentication compatible with dashboard.
        
        Examples:
        - /api/timeseries/gpu_temperature?hours=24&aggregation=max
        - /api/timeseries/cpu_usage_percent?clients=1,2&hours=6&aggregation=avg
        """
        try:
            # Calculate time range
            end_time = int(time.time())
            start_time = end_time - (hours * 3600)
            
            # Get series for the requested metric
            series_query = (MetricSeries.select()
                          .join(Client)
                          .where(MetricSeries.metric_name == metric_name))
            
            if clients:
                series_query = series_query.where(MetricSeries.client.in_(clients))
                
            series_list = list(series_query)
            if not series_list:
                return {"data": [[]], "series": [{}], "clients": {}, "metric": metric_name}
            
            # Collect all timestamps and organize by client
            timestamps = set()
            client_data = {}
            client_names = {}
            
            # Get metric points in time range (check both int and float tables)
            series_ids = [s.id for s in series_list]
            
            # Try int points first
            int_points = (MetricPointsInt.select()
                         .where(
                             (MetricPointsInt.series.in_(series_ids)) &
                             (MetricPointsInt.timestamp >= start_time) &
                             (MetricPointsInt.timestamp <= end_time)
                         )
                         .order_by(MetricPointsInt.timestamp))
            
            # Process int points
            for point in int_points:
                series = next(s for s in series_list if s.id == point.series.id)
                client_id = series.client.id
                timestamp = point.timestamp
                value = float(point.value)
                
                # Store client name
                if client_id not in client_names:
                    client_names[client_id] = series.client.hostname
                
                timestamps.add(timestamp)
                
                # Initialize client data structure
                if client_id not in client_data:
                    client_data[client_id] = {}
                
                # Apply aggregation for this timestamp
                if timestamp not in client_data[client_id]:
                    client_data[client_id][timestamp] = [value]
                else:
                    client_data[client_id][timestamp].append(value)
            
            # Try float points 
            float_points = (MetricPointsFloat.select()
                           .where(
                               (MetricPointsFloat.series.in_(series_ids)) &
                               (MetricPointsFloat.timestamp >= start_time) &
                               (MetricPointsFloat.timestamp <= end_time)
                           )
                           .order_by(MetricPointsFloat.timestamp))
            
            # Process float points
            for point in float_points:
                series = next(s for s in series_list if s.id == point.series.id)
                client_id = series.client.id
                timestamp = point.timestamp
                value = point.value
                
                # Store client name
                if client_id not in client_names:
                    client_names[client_id] = series.client.hostname
                
                timestamps.add(timestamp)
                
                # Initialize client data structure
                if client_id not in client_data:
                    client_data[client_id] = {}
                
                # Apply aggregation for this timestamp
                if timestamp not in client_data[client_id]:
                    client_data[client_id][timestamp] = [value]
                else:
                    client_data[client_id][timestamp].append(value)
            
            # Apply aggregation function to collected values
            aggregated_client_data = {}
            for client_id, time_data in client_data.items():
                aggregated_client_data[client_id] = {}
                for timestamp, values in time_data.items():
                    if aggregation == "max":
                        aggregated_client_data[client_id][timestamp] = max(values)
                    elif aggregation == "min":
                        aggregated_client_data[client_id][timestamp] = min(values)
                    elif aggregation == "avg":
                        aggregated_client_data[client_id][timestamp] = sum(values) / len(values)
                    elif aggregation == "sum":
                        aggregated_client_data[client_id][timestamp] = sum(values)
                    else:  # raw - take first value
                        aggregated_client_data[client_id][timestamp] = values[0]
            
            # Convert to uPlot format: [[timestamps], [client1_values], [client2_values], ...]
            sorted_timestamps = sorted(list(timestamps))
            uplot_data = [sorted_timestamps]  # x-axis (timestamps)
            
            # Build series configuration for uPlot
            series_config = [{}]  # x-axis config (empty)
            
            # Color palette for different clients
            colors = ["#73bf69", "#f2495c", "#5794f2", "#ff9830", "#9d7bd8", "#70dbed"]
            color_idx = 0
            
            for client_id in sorted(aggregated_client_data.keys()):
                # Build values array for this client
                values = []
                for timestamp in sorted_timestamps:
                    values.append(aggregated_client_data[client_id].get(timestamp, None))
                
                uplot_data.append(values)
                
                # Add series configuration
                series_config.append({
                    "label": client_names[client_id],
                    "stroke": colors[color_idx % len(colors)],
                    "width": 2,
                    "show": True
                })
                color_idx += 1
            
            # Determine unit based on metric name
            unit_map = {
                "gpu_temperature": "°C",
                "cpu_temp_celsius": "°C", 
                "cpu_usage_percent": "%",
                "memory_usage_percent": "%",
                "disk_usage_percent": "%",
                "gpu_power_draw": "W",
                "gpu_fan_speed": "%",
                "ipmi_fan_rpm": " RPM"
            }
            unit = unit_map.get(metric_name, "")
            
            return {
                "data": uplot_data,
                "series": series_config,
                "clients": client_names,
                "time_range": {"start": start_time, "end": end_time},
                "metric": metric_name,
                "aggregation": aggregation,
                "unit": unit
            }
            
        except Exception as e:
            logger.error(f"Error getting {metric_name} timeseries: {e}")
            raise HTTPException(status_code=500, detail="Failed to get timeseries data")

    @app.get("/api/stats", dependencies=[Depends(require_admin_auth)])
    def get_stats():
        return db_manager.get_stats()

    @app.get("/health", dependencies=[Depends(require_admin_auth)])
    def health():
        try:
            Client.select().limit(1).execute()
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "ok", "db": "connected" if db_ok else "down"}

    @app.get("/api/client/verify")
    def verify_client(client: Client = Depends(require_client_auth)):
        """Verify client authentication and return client info"""
        return {
            "status": "authenticated",
            "client_id": client.id,
            "hostname": client.hostname,
            "last_seen": client.last_seen
        }

    # ------------- Dashboard Routes & Static Files -------------
    
    # Initialize dashboard controller and templates
    dashboard_controller = DashboardController()
    templates = Jinja2Templates(directory="templates")
    
    # Add template filters for better display
    def format_datetime(timestamp):
        if not timestamp:
            return ""
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        except:
            return str(timestamp)
    
    def format_time(timestamp):
        if not timestamp:
            return ""
        try:
            return time.strftime("%H:%M:%S", time.localtime(timestamp))
        except:
            return str(timestamp)
    
    def format_time_ago(timestamp):
        if not timestamp:
            return "Never"
        try:
            diff = int(time.time()) - timestamp
            if diff < 60:
                return f"{diff}s ago"
            elif diff < 3600:
                return f"{diff // 60}m ago"
            elif diff < 86400:
                return f"{diff // 3600}h ago"
            else:
                return f"{diff // 86400}d ago"
        except:
            return "Unknown"
    
    # Add template filters and functions
    def format_bytes(bytes_value):
        if not bytes_value:
            return "0 B"
        try:
            bytes_val = float(bytes_value)
            if bytes_val < 1024:
                return f"{bytes_val:.0f}B"
            elif bytes_val < 1024**2:
                return f"{bytes_val/1024:.1f}KB"
            elif bytes_val < 1024**3:
                return f"{bytes_val/(1024**2):.1f}MB"
            else:
                return f"{bytes_val/(1024**3):.1f}GB"
        except:
            return str(bytes_value)
    
    def format_uptime_long(seconds):
        if not seconds:
            return "Unknown"
        try:
            seconds = int(seconds)
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            minutes = (seconds % 3600) // 60
            if days > 0:
                return f"{days} days, {hours} hours"
            elif hours > 0:
                return f"{hours} hours, {minutes} minutes"
            else:
                return f"{minutes} minutes"
        except:
            return "Unknown"
    
    def get_metric_status_helper(metric_name, value):
        """Template helper for getting metric status class"""
        try:
            from dashboard.config import get_metric_status
            return get_metric_status(metric_name, float(value) if value else 0)
        except:
            return 'no_data'
    
    # Add filters to Jinja2 environment
    templates.env.filters['format_datetime'] = format_datetime
    templates.env.filters['format_time'] = format_time
    templates.env.filters['format_time_ago'] = format_time_ago
    templates.env.filters['format_bytes'] = format_bytes
    templates.env.filters['format_uptime_long'] = format_uptime_long
    templates.env.globals['get_metric_status'] = get_metric_status_helper

    @app.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(require_admin_auth)])
    def dashboard_main(request: Request):
        """Main dashboard page - shows system overview, clients, and metrics."""
        logger.debug("Rendering main dashboard")
        
        try:
            dashboard_data = dashboard_controller.get_main_dashboard_data()
            dashboard_data["request"] = request
            
            return templates.TemplateResponse("dashboard.html", dashboard_data)
            
        except Exception as e:
            logger.error(f"Dashboard error: {e}")
            return templates.TemplateResponse("dashboard.html", {
                "request": request,
                "page_title": "dcmon Dashboard - Error",
                "error": str(e),
                "timestamp": int(time.time()),
                "clients": [],
                "system_overview": {},
                "recent_alerts": [],
                "charts": {}
            })

    @app.get("/dashboard/refresh/clients", response_class=HTMLResponse, dependencies=[Depends(require_admin_auth)])
    def dashboard_refresh_clients(request: Request):
        """Refresh client status table via htmx."""
        logger.debug("Refreshing client status")
        
        try:
            clients = dashboard_controller._get_client_status_data()
            return templates.TemplateResponse("components/clients_table.html", {
                "request": request,
                "clients": clients,
                "timestamp": int(time.time())
            })
            
        except Exception as e:
            logger.error(f"Client refresh error: {e}")
            return templates.TemplateResponse("components/clients_table.html", {
                "request": request,
                "clients": [],
                "error": str(e),
                "timestamp": int(time.time())
            })

    # Mount static files (CSS, JS, etc.)
    app.mount("/static", StaticFiles(directory="static"), name="static")

    return app


# ---------------- Entrypoint ----------------

def _detect_external_ip() -> str:
    """Detect current machine's external IP address"""
    import subprocess
    import socket
    
    try:
        # Try to get IP from hostname -I (most reliable for server IPs)
        result = subprocess.run(['hostname', '-I'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            # Get first IP from the output
            ip = result.stdout.strip().split()[0]
            if ip and ip != '127.0.0.1':
                return ip
    except Exception:
        pass
    
    try:
        # Fallback: connect to external host to determine our IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        pass
    
    return "127.0.0.1"


def _generate_test_certificates(cert_path, key_path) -> bool:
    """Generate self-signed certificates for test mode"""
    import subprocess
    
    try:
        external_ip = _detect_external_ip()
        logger.info(f"Auto-generating test certificates for IP: {external_ip}")
        
        # Generate certificate with both external IP and localhost
        cmd = [
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
            '-keyout', str(key_path), '-out', str(cert_path),
            '-days', '365', '-nodes', '-subj', '/CN=dcmon-server',
            '-addext', f'subjectAltName=IP:{external_ip},IP:127.0.0.1,DNS:localhost'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.error(f"Certificate generation failed: {result.stderr}")
            return False
        
        # Set proper permissions
        try:
            key_path.chmod(0o600)
            cert_path.chmod(0o644)
        except Exception as e:
            logger.warning(f"Failed to set certificate permissions: {e}")
        
        logger.info(f"Generated test certificates: cert={cert_path}, key={key_path}")
        return True
        
    except Exception as e:
        logger.error(f"Certificate generation error: {e}")
        return False


def _get_ssl_context(config: ServerConfig, cert_path, key_path):
    """Create SSL context for HTTPS if TLS is enabled and certificates exist"""
    from pathlib import Path
    import ssl
    
    if not config.use_tls:
        return None
    
    # Use resolved auth_dir paths for certificates
    cert_file = str(cert_path)
    key_file = str(key_path)
    
    # Check if certificate files exist
    if not Path(cert_file).exists() or not Path(key_file).exists():
        if config.test_mode:
            # Auto-generate certificates in test mode
            logger.info("Test mode: auto-generating HTTPS certificates")
            if not _generate_test_certificates(cert_path, key_path):
                logger.warning("Failed to generate test certificates. Server will start without TLS.")
                return None
        else:
            # Production mode: require existing certificates
            logger.warning("TLS enabled but certificate files not found: cert=%s, key=%s", cert_file, key_file)
            logger.warning("Server will start without TLS. Generate certificates or set use_tls=false")
            return None
    
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(cert_file, key_file)
    logger.info("TLS enabled with cert=%s, key=%s", cert_file, key_file)
    return ssl_context


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="dcmon server")
    parser.add_argument("-c", "--config", help="Path to YAML config", default="config.yaml")
    args = parser.parse_args()

    config = load_config_from(args.config)
    
    # Resolve certificate paths for SSL context
    _, _, _, cert_path, key_path = _resolve_paths(config)
    ssl_context = _get_ssl_context(config, cert_path, key_path)
    
    app = create_app(config)

    import uvicorn
    
    # Prepare uvicorn kwargs
    uvicorn_kwargs = {
        "host": config.host,
        "port": config.port, 
        "reload": False,
        "access_log": False
    }
    
    # Add SSL parameters if TLS is enabled
    if ssl_context:
        uvicorn_kwargs.update({
            "ssl_keyfile": str(key_path),
            "ssl_certfile": str(cert_path)
        })
    
    uvicorn.run(app, **uvicorn_kwargs)
