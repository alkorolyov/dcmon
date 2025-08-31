#!/usr/bin/env python3
"""
API Routes for dcmon Server
"""

import time
import json
import logging
from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from models import DatabaseManager, Client, Metric, Command, get_db
from auth import get_server_auth

logger = logging.getLogger('dcmon-server')
security = HTTPBearer()

# Pydantic models
class ClientRegistration(BaseModel):
    admin_token: str
    machine_id: str
    hostname: str
    public_key: str
    challenge: str
    timestamp: int
    signature: str

class MetricSubmission(BaseModel):
    metrics: List[Dict[str, Any]]
    timestamp: int

class CommandRequest(BaseModel):
    machine_id: str
    command_type: str
    command_data: Dict[str, Any]

class CommandResult(BaseModel):
    machine_id: str
    command_id: str
    timestamp: int
    result: Dict[str, Any]

def create_auth_dependency(admin_token: str):
    """Create authentication dependency with the given admin token"""
    async def auth_dependency(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
        """Authenticate admin requests"""
        if credentials.credentials != admin_token:
            raise HTTPException(status_code=401, detail="Invalid admin token")
        return True
    return auth_dependency

async def get_current_client(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Client:
    """Authenticate client by client token"""
    token = credentials.credentials
    
    db_manager = get_db()
    client = db_manager.get_client_by_token(token)
    if not client:
        raise HTTPException(status_code=401, detail="Invalid client token")
    
    # Update last seen
    db_manager.update_client_last_seen(client.machine_id)
    return client

def create_routes(admin_token: str) -> APIRouter:
    """Create API router with all routes"""
    router = APIRouter()
    
    # Create admin authentication dependency
    get_admin_auth = create_auth_dependency(admin_token)
    
    @router.get("/")
    async def root(admin_auth: bool = Depends(get_admin_auth)):
        """Root endpoint (admin only)"""
        return {"message": "dcmon Server V2", "version": "2.0.0"}

    @router.get("/health")
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

    @router.post("/api/register")
    async def register_client(request: ClientRegistration):
        """Register a new client using V2 key-based authentication"""
        try:
            server_auth = get_server_auth()
            if not server_auth:
                raise HTTPException(status_code=500, detail="Server authentication not available")
            
            # Validate admin token
            if request.admin_token != admin_token:
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
            
            # Generate client token
            client_token = server_auth.generate_client_token(machine_id, public_key)
            
            # Store client in database
            db_manager = get_db()
            if db_manager.register_client(machine_id, hostname, client_token):
                logger.info(f"Client registered: {machine_id} ({hostname})")
                return {
                    "status": "registered",
                    "machine_id": machine_id,
                    "client_token": client_token,
                    "message": "Client registration successful"
                }
            else:
                raise HTTPException(status_code=400, detail="Client already registered")
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Registration failed: {e}")
            raise HTTPException(status_code=500, detail="Registration failed")

    @router.get("/api/clients")
    async def get_clients(admin_auth: bool = Depends(get_admin_auth)):
        """Get list of all registered clients (admin only)"""
        try:
            db_manager = get_db()
            clients = db_manager.get_all_clients()
            
            client_list = []
            for client in clients:
                client_list.append({
                    "machine_id": client.machine_id,
                    "hostname": client.hostname,
                    "last_seen": client.last_seen,
                    "status": client.status
                })
            
            return {"clients": client_list, "count": len(client_list)}
        except Exception as e:
            logger.error(f"Failed to get clients: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.get("/api/stats")
    async def get_stats(admin_auth: bool = Depends(get_admin_auth)):
        """Get server statistics (admin only)"""
        try:
            db_manager = get_db()
            return db_manager.get_stats()
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post("/api/metrics")
    async def submit_metrics(
        request: MetricSubmission, 
        current_client: Client = Depends(get_current_client)
    ):
        """Submit metrics from client"""
        try:
            db_manager = get_db()
            metrics = []
            
            for metric_data in request.metrics:
                # Determine if we should store as integer
                metric_name = metric_data.get('metric_name', '')
                value = metric_data.get('value', 0)
                
                if should_store_as_integer(metric_name):
                    value_int = int(value) if isinstance(value, (int, float)) else None
                    value_float = None
                else:
                    value_int = None
                    value_float = float(value) if isinstance(value, (int, float)) else 0.0
                
                metric = Metric(
                    machine_id=current_client.machine_id,
                    timestamp=metric_data.get('timestamp', int(time.time())),
                    metric_name=metric_name,
                    value=value_float,
                    value_int=value_int,
                    labels=json.dumps(metric_data.get('labels', {}))
                )
                metrics.append(metric)
            
            count = db_manager.store_metrics(metrics)
            return {
                "status": "success",
                "metrics_stored": count,
                "timestamp": int(time.time())
            }
        except Exception as e:
            logger.error(f"Failed to store metrics: {e}")
            raise HTTPException(status_code=500, detail="Failed to store metrics")

    @router.get("/api/metrics")
    async def get_metrics(
        machine_id: str = None,
        metric_name: str = None,
        start_time: int = None,
        end_time: int = None,
        limit: int = 1000,
        admin_auth: bool = Depends(get_admin_auth)
    ):
        """Get metrics with optional filtering (admin only)"""
        try:
            db_manager = get_db()
            
            # Build query parameters
            filters = {}
            if machine_id:
                filters['machine_id'] = machine_id
            if metric_name:
                filters['metric_name'] = metric_name
            if start_time:
                filters['start_time'] = start_time
            if end_time:
                filters['end_time'] = end_time
                
            metrics = db_manager.get_metrics(filters, limit)
            
            result = []
            for metric in metrics:
                result.append({
                    "machine_id": metric.machine_id,
                    "timestamp": metric.timestamp,
                    "metric_name": metric.metric_name,
                    "value": metric.value if metric.value is not None else metric.value_int,
                    "labels": json.loads(metric.labels) if metric.labels else {}
                })
            
            return {"metrics": result, "count": len(result)}
        except Exception as e:
            logger.error(f"Failed to get metrics: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.get("/api/commands/{machine_id}")
    async def get_pending_commands(
        machine_id: str,
        current_client: Client = Depends(get_current_client)
    ):
        """Get pending commands for client"""
        # Verify client is requesting their own commands
        if current_client.machine_id != machine_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        try:
            db_manager = get_db()
            commands = db_manager.get_pending_commands(machine_id)
            
            command_list = []
            for command in commands:
                command_list.append({
                    "id": command.id,
                    "command_type": command.command_type,
                    "command_data": json.loads(command.command_data) if command.command_data else {},
                    "created_at": command.created_at
                })
            
            return {"commands": command_list}
        except Exception as e:
            logger.error(f"Failed to get commands for {machine_id}: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post("/api/commands")
    async def create_command(
        request: CommandRequest,
        admin_auth: bool = Depends(get_admin_auth)
    ):
        """Create a command for a client (admin only)"""
        try:
            db_manager = get_db()
            
            # Verify client exists
            client = db_manager.get_client(request.machine_id)
            if not client:
                raise HTTPException(status_code=404, detail="Client not found")
            
            command = Command(
                machine_id=request.machine_id,
                command_type=request.command_type,
                command_data=json.dumps(request.command_data),
                status="pending",
                created_at=int(time.time())
            )
            
            command_id = db_manager.create_command(command)
            if command_id:
                return {
                    "status": "created",
                    "command_id": command_id,
                    "machine_id": request.machine_id
                }
            else:
                raise HTTPException(status_code=500, detail="Failed to create command")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to create command: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post("/api/command-results")
    async def submit_command_result(
        request: CommandResult,
        current_client: Client = Depends(get_current_client)
    ):
        """Submit command execution result from client"""
        # Verify client is submitting result for their own command
        if current_client.machine_id != request.machine_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        try:
            db_manager = get_db()
            success = db_manager.update_command_result(
                request.command_id,
                "completed",
                json.dumps(request.result),
                request.timestamp
            )
            
            if success:
                return {"status": "success"}
            else:
                raise HTTPException(status_code=404, detail="Command not found")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update command result: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    return router

def should_store_as_integer(metric_name: str) -> bool:
    """Determine if a metric should be stored as integer for space efficiency"""
    integer_metrics = {
        'memory_total_bytes', 'memory_available_bytes', 'memory_used_bytes',
        'disk_total_bytes', 'disk_used_bytes', 'disk_free_bytes',
        'network_receive_bytes_total', 'network_transmit_bytes_total',
        'network_receive_packets_total', 'network_transmit_packets_total',
        'gpu_memory_total_bytes', 'gpu_memory_used_bytes', 'gpu_memory_free_bytes',
        'gpu_clock_sm', 'gpu_clock_memory', 'gpu_power_draw_watts',
        'apt_upgrades_pending', 'apt_security_upgrades_pending',
        'process_count', 'load_average_1m', 'load_average_5m', 'load_average_15m',
        'cpu_count', 'boot_time'
    }
    return metric_name in integer_metrics