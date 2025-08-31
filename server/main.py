#!/usr/bin/env python3
"""
dcmon Server - Clean V2 Implementation with Peewee
Simplified version focusing on V2 authentication
"""

import logging
import time
import json
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from models import DatabaseManager, Client, Metric, Command, get_db
from auth import get_server_auth

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('dcmon-server')

# Security
security = HTTPBearer()

# Load admin key
def load_admin_token() -> str:
    """Load admin token from file"""
    try:
        with open("/etc/dcmon-server/admin_token", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        # For testing, generate a simple key
        logger.warning("Admin token file not found, using test token")
        return "dcmon_admin_test123"
    except Exception as e:
        logger.error(f"Failed to load admin token: {e}")
        raise

ADMIN_TOKEN = load_admin_token()
logger.info("Admin token loaded successfully")

# Authentication
async def get_admin_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    """Authenticate admin requests"""
    if credentials.credentials != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return True

async def get_current_client(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Client:
    """Authenticate client by client token"""
    token = credentials.credentials
    client = Client.get_by_client_token(token)
    
    if not client:
        raise HTTPException(status_code=401, detail="Invalid client token")
    
    if client.status != 'active':
        raise HTTPException(status_code=403, detail="Client is not active")
    
    return client

# Pydantic models
class ClientRegistration(BaseModel):
    machine_id: str
    hostname: str
    public_key: str
    challenge: str
    signature: str
    timestamp: int
    auth_version: str = "v2"
    admin_token: str


class MetricData(BaseModel):
    name: str
    value: float
    timestamp: int
    labels: Dict[str, str] = None

class MetricsSubmission(BaseModel):
    machine_id: str
    timestamp: int
    metrics: List[MetricData]

class CommandRequest(BaseModel):
    machine_id: str
    command_type: str
    command_data: Dict[str, Any]

class CommandResult(BaseModel):
    machine_id: str
    command_id: str
    timestamp: int
    result: Dict[str, Any]

# FastAPI app
app = FastAPI(
    title="dcmon Server V2",
    description="Datacenter Monitoring Server with V2 Authentication",
    version="2.0.0"
)

@app.on_event("startup") 
async def startup_event():
    """Initialize database on startup"""
    from models import DatabaseManager
    
    db_path = "/var/lib/dcmon/dcmon.db"
    global db_manager
    db_manager = DatabaseManager(db_path)
    
    if not db_manager.connect():
        raise RuntimeError("Failed to initialize database")
    logger.info(f"dcmon server V2 started with database: {db_path}")

@app.on_event("shutdown")
async def shutdown_event():
    """Close database on shutdown"""
    db_manager = get_db()
    db_manager.close()
    logger.info("dcmon server V2 stopped")

# API Routes
@app.get("/")
async def root(admin_auth: bool = Depends(get_admin_auth)):
    """Root endpoint (admin only)"""
    return {"message": "dcmon Server V2", "version": "2.0.0"}

@app.get("/health")
async def health_check(admin_auth: bool = Depends(get_admin_auth)):
    """Health check endpoint (admin only)"""
    try:
        db_manager = get_db()
        stats = db_manager.get_stats()
        return {
            "status": "healthy",
            "timestamp": int(time.time()),
            "database": stats
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")

@app.post("/api/register")
async def register_client(request: ClientRegistration):
    """Register a new client using V2 key-based authentication"""
    try:
        server_auth = get_server_auth()
        if not server_auth:
            raise HTTPException(status_code=500, detail="Server authentication not available")
        
        # Validate admin token
        if request.admin_token != ADMIN_TOKEN:
            raise HTTPException(status_code=401, detail="Invalid admin token")
        
        # Validate the registration payload
        request_dict = request.model_dump()
        validation_result = server_auth.validate_registration_payload(request_dict)
        if not validation_result['valid']:
            logger.warning(f"Registration validation failed: {validation_result['error']}")
            raise HTTPException(status_code=400, detail=validation_result['error'])
        
        machine_id = validation_result['machine_id']
        hostname = validation_result['hostname'] 
        public_key = validation_result['public_key']
        
        # Check if client already exists
        existing_client = Client.get_or_none(Client.machine_id == machine_id)
        if existing_client:
            # Update public key and generate new client token
            client_token = server_auth.generate_client_token(machine_id, public_key)
            existing_client.client_token = client_token
            existing_client.public_key = public_key
            existing_client.hostname = hostname
            existing_client.last_seen = int(time.time())
            existing_client.save()
                
            logger.info(f"Updated existing client: {machine_id}")
            return {
                "message": "Client updated successfully",
                "client_token": client_token,
                "machine_id": machine_id
            }
        
        # Create new client
        client_token = server_auth.generate_client_token(machine_id, public_key)
        client = Client.create(
            machine_id=machine_id,
            client_token=client_token,
            hostname=hostname,
            public_key=public_key,
            last_seen=int(time.time()),
            created_at=int(time.time())
        )
        
        logger.info(f"Registered new client: {machine_id}")
        
        return {
            "message": "Client registered successfully", 
            "client_token": client_token,
            "machine_id": machine_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Client registration failed: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")

@app.get("/api/clients")
async def get_clients(admin_auth: bool = Depends(get_admin_auth)):
    """Get all registered clients (admin endpoint)"""
    try:
        clients = Client.get_active_clients()
        return {
            "clients": [client.to_dict() for client in clients],
            "count": len(clients),
            "timestamp": int(time.time())
        }
    except Exception as e:
        logger.error(f"Failed to get clients: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve clients")

@app.get("/api/stats")
async def get_server_stats(admin_auth: bool = Depends(get_admin_auth)):
    """Get server statistics (admin endpoint)"""
    try:
        db_manager = get_db()
        stats = db_manager.get_stats()
        stats.update({
            "server_uptime": int(time.time()),
            "version": "2.0.0"
        })
        return stats
    except Exception as e:
        logger.error(f"Failed to get server stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get statistics")

# Metrics endpoints
@app.post("/api/metrics")
async def submit_metrics(submission: MetricsSubmission, current_client: Client = Depends(get_current_client)):
    """Submit metrics from client"""
    try:
        # Verify machine_id matches authenticated client
        if submission.machine_id != current_client.machine_id:
            raise HTTPException(status_code=403, detail="Machine ID mismatch")
        
        # Store metrics using Peewee
        for metric_data in submission.metrics:
            # Determine if should be stored as integer
            value_int = None
            if is_integer_metric(metric_data.name) and isinstance(metric_data.value, (int, float)):
                if metric_data.value == int(metric_data.value):
                    value_int = int(metric_data.value)
            
            Metric.create(
                machine_id=submission.machine_id,
                timestamp=metric_data.timestamp,
                metric_name=metric_data.name,
                value=metric_data.value,
                value_int=value_int,
                labels=json.dumps(metric_data.labels) if metric_data.labels else None
            )
        
        # Update client last seen
        current_client.update_last_seen(submission.timestamp)
        
        logger.debug(f"Stored {len(submission.metrics)} metrics from {submission.machine_id}")
        
        return {
            "status": "accepted",
            "metrics_count": len(submission.metrics),
            "timestamp": int(time.time())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to submit metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to process metrics")

@app.get("/api/metrics")
async def get_metrics(
    admin_auth: bool = Depends(get_admin_auth),
    machine_id: str = None,
    metric_names: str = None,
    start_time: int = None,
    end_time: int = None,
    limit: int = 1000
):
    """Query metrics (admin endpoint)"""
    try:
        # Parse metric names
        metric_name_list = None
        if metric_names:
            metric_name_list = [name.strip() for name in metric_names.split(',')]
        
        # Query metrics using Peewee
        metrics = Metric.get_metrics(
            machine_id=machine_id,
            metric_names=metric_name_list,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )
        
        # Convert to response format
        result = [metric.to_dict() for metric in metrics]
        
        return {
            "metrics": result,
            "count": len(result),
            "query_time": int(time.time())
        }
        
    except Exception as e:
        logger.error(f"Failed to query metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to query metrics")

# Command endpoints
@app.get("/api/commands/{machine_id}")
async def get_commands(machine_id: str, current_client: Client = Depends(get_current_client)):
    """Get pending commands for client"""
    try:
        # Verify machine_id matches authenticated client
        if machine_id != current_client.machine_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Get pending commands using Peewee
        commands = Command.get_pending_for_client(machine_id)
        
        # Convert to response format
        command_list = []
        for cmd in commands:
            command_list.append({
                "id": cmd.id,
                "type": cmd.command_type,
                "params": json.loads(cmd.command_data),
                "created_at": cmd.created_at
            })
        
        return {
            "commands": command_list,
            "count": len(command_list),
            "timestamp": int(time.time())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get commands for {machine_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve commands")

@app.post("/api/commands")
async def create_command(command_request: CommandRequest, admin_auth: bool = Depends(get_admin_auth)):
    """Create a new command for client (admin endpoint)"""
    try:
        # Verify target client exists
        target_client = Client.get_or_none(Client.machine_id == command_request.machine_id)
        if not target_client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        # Create command using Peewee
        import uuid
        command_id = f"cmd_{uuid.uuid4().hex[:8]}"
        
        command = Command.create(
            id=command_id,
            machine_id=command_request.machine_id,
            command_type=command_request.command_type,
            command_data=json.dumps(command_request.command_data),
            created_at=int(time.time())
        )
        
        logger.info(f"Created command {command_id} for {command_request.machine_id}")
        
        return {
            "command_id": command_id,
            "status": "created",
            "timestamp": int(time.time())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create command: {e}")
        raise HTTPException(status_code=500, detail="Failed to create command")

@app.post("/api/command-results")
async def submit_command_result(result_data: CommandResult, current_client: Client = Depends(get_current_client)):
    """Submit command execution result from client"""
    try:
        # Verify machine_id matches authenticated client
        if result_data.machine_id != current_client.machine_id:
            raise HTTPException(status_code=403, detail="Machine ID mismatch")
        
        # Update command with result using Peewee
        command = Command.get_or_none(Command.id == result_data.command_id)
        if not command:
            raise HTTPException(status_code=404, detail="Command not found")
        
        if result_data.result.get('success', False):
            command.mark_completed(result_data.result)
        else:
            command.mark_failed(result_data.result.get('message', 'Unknown error'))
        
        logger.info(f"Updated command {result_data.command_id} result: {command.status}")
        
        return {
            "status": "accepted",
            "timestamp": int(time.time())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to submit command result: {e}")
        raise HTTPException(status_code=500, detail="Failed to process command result")

# Utility functions
def is_integer_metric(metric_name: str) -> bool:
    """Determine if a metric should be stored as integer"""
    integer_metrics = {
        'memory_total_bytes', 'memory_available_bytes', 'memory_used_bytes',
        'disk_read_bytes_total', 'disk_write_bytes_total',
        'network_receive_bytes_total', 'network_transmit_bytes_total',
        'gpu_memory_total', 'gpu_memory_used', 'gpu_clock_sm', 'gpu_clock_mem',
        'apt_upgrades_pending', 'apt_security_upgrades_pending',
        'nvme_bytes_read', 'nvme_bytes_written',
        'cpu_count', 'boot_time'
    }
    return metric_name in integer_metrics

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)