#!/usr/bin/env python3
"""
WebSocket Command Routes - Real-time Command Execution
"""

import json
import logging
import asyncio
import websockets
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
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
            result = await execute_websocket_command(
                client_id=request.client_id,
                command_type=request.command_type,
                command_data=request.command_data
            )
            
            logger.info(f"Command executed successfully on client {request.client_id}")
            return {"status": "success", "result": result}
            
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            raise HTTPException(status_code=500, detail=f"command execution failed: {str(e)}")

    @router.websocket("/ws/command/{client_id}")
    async def command_websocket(websocket: WebSocket, client_id: int):
        """WebSocket endpoint for command execution."""
        await websocket.accept()
        
        try:
            # TODO: Add client authentication here
            # For now, accept any connection to client_id
            
            logger.info(f"WebSocket command connection established for client {client_id}")
            
            # Keep connection alive and handle commands
            while True:
                try:
                    # Wait for command from server
                    message = await websocket.receive_json()
                    
                    # Execute command and send result back
                    # Client should send result back via websocket
                    result = await websocket.receive_json()
                    
                    # For now, just echo back
                    await websocket.send_json({"status": "received", "result": result})
                    
                except WebSocketDisconnect:
                    logger.info(f"WebSocket disconnected for client {client_id}")
                    break
                except Exception as e:
                    logger.error(f"WebSocket error for client {client_id}: {e}")
                    await websocket.send_json({"status": "error", "error": str(e)})
                    
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
        finally:
            logger.info(f"WebSocket connection closed for client {client_id}")

    return router


async def execute_websocket_command(client_id: int, command_type: str, command_data: Dict[str, Any]) -> Dict[str, Any]:
    """Execute command on client via WebSocket connection."""
    # TODO: Implement WebSocket client connection to send commands
    # For now, return mock result
    
    logger.info(f"Executing {command_type} command on client {client_id}")
    
    # Simulate command execution
    await asyncio.sleep(0.1)
    
    return {
        "command_type": command_type,
        "command_data": command_data,
        "execution_time": 0.1,
        "success": True
    }