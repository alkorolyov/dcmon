#!/usr/bin/env python3
"""
WebSocket Command Routes - Real-time Command Execution
"""

import json
import logging
import asyncio
import websockets
import uuid
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from pydantic import BaseModel

# Support running as script or as package
try:
    from ...models import Client
    from ..dependencies import AuthDependencies
    from ...core.audit import audit_logger
except ImportError:
    from models import Client
    from api.dependencies import AuthDependencies
    from core.audit import audit_logger

logger = logging.getLogger("dcmon.server")


class CommandRequest(BaseModel):
    """Request to execute command on client"""
    client_id: int
    command_type: str  # 'fan_control', 'ipmi_raw', etc.
    command_data: Dict[str, Any]


def create_command_routes(auth_deps: AuthDependencies) -> APIRouter:
    """Create WebSocket-based command routes."""
    router = APIRouter()

    @router.post("/api/commands", dependencies=[Depends(auth_deps.require_admin_auth)])
    async def execute_command(request: CommandRequest):
        """Execute command via WebSocket immediately."""
        try:
            # Verify client exists
            client = Client.get_by_id(request.client_id)
        except Client.DoesNotExist:
            raise HTTPException(status_code=404, detail="client not found")

        # Log admin action
        audit_logger.admin_action(
            action="execute_command",
            details={
                "client_id": request.client_id,
                "command_type": request.command_type,
                "hostname": client.hostname
            },
            request=None
        )

        try:
            # Execute command via WebSocket
            result = await send_command_to_client(
                client_id=request.client_id,
                command_type=request.command_type,
                command_data=request.command_data
            )
            
            logger.info(f"Command executed successfully on client {request.client_id}")
            return {"status": "success", "result": result}
            
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            raise HTTPException(status_code=500, detail=f"command execution failed: {str(e)}")

    # Individual REST endpoints for specific commands
    @router.post("/api/clients/{client_id}/command/fan-mode", dependencies=[Depends(auth_deps.require_admin_auth)])
    async def set_fan_mode(client_id: int, request: Request):
        """Set fan mode on client."""
        try:
            body = await request.json()
            mode = body.get("mode")
            
            if not mode:
                raise HTTPException(status_code=400, detail="mode is required")
            
            result = await send_command_to_client(
                client_id=client_id,
                command_type="fan_control",
                command_data={"action": "set_mode", "mode": mode}
            )
            return {"status": "success", "mode": mode, "result": result}
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Fan mode command failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/clients/{client_id}/command/fan-status", dependencies=[Depends(auth_deps.require_admin_auth)])
    async def get_fan_status(client_id: int):
        """Get fan status from client."""
        try:
            result = await send_command_to_client(
                client_id=client_id,
                command_type="fan_control",
                command_data={"action": "get_status"}
            )
            return {"status": "success", "result": result}
            
        except Exception as e:
            logger.error(f"Fan status command failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/clients/{client_id}/command/system-info/{info_type}", dependencies=[Depends(auth_deps.require_admin_auth)])
    async def get_system_info(client_id: int, info_type: str):
        """Get system information from client."""
        try:
            valid_types = ["basic", "hardware", "network"]
            if info_type not in valid_types:
                raise HTTPException(status_code=400, detail=f"Invalid info type. Must be one of: {valid_types}")
            
            result = await send_command_to_client(
                client_id=client_id,
                command_type="system_info",
                command_data={"type": info_type}
            )
            return {"status": "success", "type": info_type, "result": result}
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"System info command failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/clients/{client_id}/command/ipmi-raw", dependencies=[Depends(auth_deps.require_admin_auth)])
    async def execute_ipmi_raw(client_id: int, request: Request):
        """Execute raw IPMI command on client."""
        try:
            body = await request.json()
            command = body.get("command")
            
            if not command:
                raise HTTPException(status_code=400, detail="command is required")
            
            result = await send_command_to_client(
                client_id=client_id,
                command_type="ipmi_raw",
                command_data={"command": command}
            )
            return {"status": "success", "command": command, "result": result}
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"IPMI raw command failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # Store active client WebSocket connections
    active_client_connections: Dict[int, WebSocket] = {}
    
    @router.websocket("/ws/client/{client_id}")
    async def client_websocket(websocket: WebSocket, client_id: int):
        """WebSocket endpoint where clients connect for command reception."""
        await websocket.accept()
        
        try:
            logger.info(f"Client {client_id} connected to command WebSocket")
            
            # Store the connection
            active_client_connections[client_id] = websocket
            logger.info(f"Active WebSocket connections: {list(active_client_connections.keys())}")
            
            # Wait for disconnection only - no message handling loop
            try:
                while True:
                    await asyncio.sleep(1)
                    # Check if websocket is still connected
                    if websocket.client_state.name != 'CONNECTED':
                        break
            except WebSocketDisconnect:
                logger.info(f"Client {client_id} disconnected from command WebSocket")
            
        except Exception as e:
            logger.error(f"Client WebSocket error: {e}")
        finally:
            # Remove connection when client disconnects
            if client_id in active_client_connections:
                del active_client_connections[client_id]
            logger.info(f"Client {client_id} WebSocket connection closed")
    
    async def send_command_to_client(client_id: int, command_type: str, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send command to connected client via WebSocket."""
        if client_id not in active_client_connections:
            connected_clients = list(active_client_connections.keys())
            logger.warning(f"Client {client_id} not in active connections. Active clients: {connected_clients}")
            raise Exception(f"Client {client_id} is not connected via WebSocket. Active clients: {connected_clients}")
        
        websocket = active_client_connections[client_id]
        
        try:
            # Send command to client
            await websocket.send_json({
                "command_type": command_type,
                "command_data": command_data
            })
            
            # Wait for response
            response = await websocket.receive_json()
            return response.get("result", {})
            
        except WebSocketDisconnect:
            del active_client_connections[client_id]
            raise Exception(f"Client {client_id} disconnected during command execution")
        except Exception as e:
            raise Exception(f"Failed to send command to client {client_id}: {str(e)}")

    return router



