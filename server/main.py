#!/usr/bin/env python3
"""
dcmon Server - Datacenter Monitoring Server
FastAPI-based server for collecting and managing client metrics
"""

import asyncio
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Any

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import Database, Client, Command, MetricPoint

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('dcmon-server')

# Global database instance
db: Optional[Database] = None
security = HTTPBearer()

# Pydantic models for API
class ClientRegistration(BaseModel):
    machine_id: str
    hostname: Optional[str] = None
    client_info: Optional[Dict[str, Any]] = None

class MetricData(BaseModel):
    name: str
    value: float
    timestamp: int
    labels: Optional[Dict[str, str]] = None

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

class ClientInfo(BaseModel):
    machine_id: str
    hostname: Optional[str] = None
    last_seen: Optional[int] = None
    status: str
    created_at: Optional[int] = None

# Database lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection lifecycle"""
    global db
    
    # Startup
    db = Database()
    await db.connect()
    
    # Start background tasks
    cleanup_task = asyncio.create_task(periodic_cleanup())
    
    logger.info("dcmon server started")
    
    try:
        yield
    finally:
        # Shutdown
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        
        if db:
            await db.close()
        logger.info("dcmon server stopped")

# Create FastAPI app
app = FastAPI(
    title="dcmon Server",
    description="Datacenter Monitoring Server API",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Authentication dependency
async def get_current_client(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Client:
    """Authenticate client by API key"""
    api_key = credentials.credentials
    client = await db.get_client_by_api_key(api_key)
    
    if not client:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if client.status != 'active':
        raise HTTPException(status_code=403, detail="Client is not active")
    
    return client

# Background tasks
async def periodic_cleanup():
    """Periodic database cleanup task"""
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            await db.cleanup_old_data(days_to_keep=7)
            logger.info("Performed periodic cleanup")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Cleanup task failed: {e}")

# Utility functions
def generate_api_key() -> str:
    """Generate a secure API key"""
    return f"dcmon_{secrets.token_urlsafe(32)}"

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

# API Routes

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "dcmon Server", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        stats = await db.get_database_stats()
        return {
            "status": "healthy",
            "timestamp": int(time.time()),
            "database": stats
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")

# Client registration and management
@app.post("/api/register")
async def register_client(registration: ClientRegistration):
    """Register a new client and return API key"""
    try:
        # Check if client already exists
        existing_client = await db.get_client(registration.machine_id)
        if existing_client:
            return {
                "message": "Client already registered",
                "api_key": existing_client.api_key,
                "machine_id": registration.machine_id
            }
        
        # Create new client
        api_key = generate_api_key()
        client = Client(
            machine_id=registration.machine_id,
            api_key=api_key,
            hostname=registration.hostname,
            client_info=str(registration.client_info) if registration.client_info else None,
            last_seen=int(time.time()),
            created_at=int(time.time())
        )
        
        success = await db.register_client(client)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to register client")
        
        logger.info(f"Registered new client: {registration.machine_id}")
        
        return {
            "message": "Client registered successfully",
            "api_key": api_key,
            "machine_id": registration.machine_id
        }
        
    except Exception as e:
        logger.error(f"Client registration failed: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")

@app.get("/api/clients", response_model=List[ClientInfo])
async def get_clients():
    """Get all registered clients (admin endpoint)"""
    try:
        clients = await db.get_all_clients()
        return [
            ClientInfo(
                machine_id=client.machine_id,
                hostname=client.hostname,
                last_seen=client.last_seen,
                status=client.status,
                created_at=client.created_at
            )
            for client in clients
        ]
    except Exception as e:
        logger.error(f"Failed to get clients: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve clients")

# Metrics handling
@app.post("/api/metrics")
async def submit_metrics(
    submission: MetricsSubmission,
    background_tasks: BackgroundTasks,
    current_client: Client = Depends(get_current_client)
):
    """Submit metrics from client"""
    try:
        # Verify machine_id matches authenticated client
        if submission.machine_id != current_client.machine_id:
            raise HTTPException(status_code=403, detail="Machine ID mismatch")
        
        # Convert submission to MetricPoint objects
        metric_points = []
        for metric_data in submission.metrics:
            # Determine if this should be stored as integer
            value_int = None
            if is_integer_metric(metric_data.name) and isinstance(metric_data.value, (int, float)):
                if metric_data.value == int(metric_data.value):
                    value_int = int(metric_data.value)
            
            metric_point = MetricPoint(
                machine_id=submission.machine_id,
                timestamp=metric_data.timestamp,
                metric_name=metric_data.name,
                value=metric_data.value,
                value_int=value_int,
                labels=str(metric_data.labels) if metric_data.labels else None
            )
            metric_points.append(metric_point)
        
        # Store metrics
        success = await db.store_metrics(metric_points)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to store metrics")
        
        # Update client last seen timestamp
        background_tasks.add_task(
            db.update_client_last_seen, 
            current_client.machine_id, 
            submission.timestamp
        )
        
        logger.debug(f"Stored {len(metric_points)} metrics from {submission.machine_id}")
        
        return {
            "status": "accepted",
            "metrics_count": len(metric_points),
            "timestamp": int(time.time())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to submit metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to process metrics")

@app.get("/api/metrics")
async def get_metrics(
    machine_id: Optional[str] = None,
    metric_names: Optional[str] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    limit: int = 1000
):
    """Query metrics (admin endpoint)"""
    try:
        # Parse metric names
        metric_name_list = None
        if metric_names:
            metric_name_list = [name.strip() for name in metric_names.split(',')]
        
        # Query metrics
        metrics = await db.get_metrics(
            machine_id=machine_id,
            metric_names=metric_name_list,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )
        
        # Convert to response format
        result = []
        for metric in metrics:
            result.append({
                "machine_id": metric.machine_id,
                "timestamp": metric.timestamp,
                "metric_name": metric.metric_name,
                "value": metric.value,
                "value_int": metric.value_int,
                "labels": metric.labels
            })
        
        return {
            "metrics": result,
            "count": len(result),
            "query_time": int(time.time())
        }
        
    except Exception as e:
        logger.error(f"Failed to query metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to query metrics")

# Command handling
@app.get("/api/commands/{machine_id}")
async def get_commands(
    machine_id: str,
    current_client: Client = Depends(get_current_client)
):
    """Get pending commands for client"""
    try:
        # Verify machine_id matches authenticated client
        if machine_id != current_client.machine_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Get pending commands
        commands = await db.get_pending_commands(machine_id)
        
        # Convert to response format
        command_list = []
        for cmd in commands:
            import json
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
async def create_command(command_request: CommandRequest):
    """Create a new command for client (admin endpoint)"""
    try:
        import json
        
        # Verify target client exists
        target_client = await db.get_client(command_request.machine_id)
        if not target_client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        # Create command
        command_id = f"cmd_{uuid.uuid4().hex[:8]}"
        command = Command(
            id=command_id,
            machine_id=command_request.machine_id,
            command_type=command_request.command_type,
            command_data=json.dumps(command_request.command_data),
            created_at=int(time.time())
        )
        
        success = await db.create_command(command)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to create command")
        
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
async def submit_command_result(
    result_data: CommandResult,
    current_client: Client = Depends(get_current_client)
):
    """Submit command execution result from client"""
    try:
        # Verify machine_id matches authenticated client
        if result_data.machine_id != current_client.machine_id:
            raise HTTPException(status_code=403, detail="Machine ID mismatch")
        
        # Update command with result
        status = 'completed' if result_data.result.get('success', False) else 'failed'
        success = await db.update_command_result(
            result_data.command_id,
            result_data.result,
            status
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update command result")
        
        logger.info(f"Updated command {result_data.command_id} result: {status}")
        
        return {
            "status": "accepted",
            "timestamp": int(time.time())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to submit command result: {e}")
        raise HTTPException(status_code=500, detail="Failed to process command result")

# Server management endpoints
@app.get("/api/stats")
async def get_server_stats():
    """Get server statistics (admin endpoint)"""
    try:
        stats = await db.get_database_stats()
        stats.update({
            "server_uptime": int(time.time()),
            "version": "1.0.0"
        })
        return stats
    except Exception as e:
        logger.error(f"Failed to get server stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get statistics")

# Main entry point
def main():
    """Main entry point"""
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        access_log=True,
        log_level="info"
    )

if __name__ == "__main__":
    main()