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
    logger.info(f"Executing {command_type} command on client {client_id}")
    
    try:
        # Get client info to determine WebSocket connection details
        client = Client.get_by_id(client_id)
        
        # For now, assume client WebSocket is running on port 9000
        # In a real implementation, we'd store this info during client registration
        client_ws_url = f"ws://localhost:9000"  # This should be dynamic based on client
        
        # Connect to client WebSocket server
        timeout_seconds = 10
        async with websockets.connect(client_ws_url, timeout=timeout_seconds) as websocket:
            # Send authentication
            auth_message = {
                "client_token": "mock_token_for_now"  # TODO: Get real client token
            }
            await websocket.send(json.dumps(auth_message))
            
            # Wait for auth response
            auth_response = await websocket.recv()
            auth_data = json.loads(auth_response)
            
            if auth_data.get("status") != "authenticated":
                raise Exception("Client authentication failed")
            
            # Send command
            command_message = {
                "command_type": command_type,
                "command_data": command_data
            }
            await websocket.send(json.dumps(command_message))
            
            # Wait for result
            result_message = await websocket.recv()
            result_data = json.loads(result_message)
            
            if result_data.get("status") == "completed":
                return result_data.get("result", {})
            else:
                raise Exception(f"Command failed: {result_data.get('error', 'Unknown error')}")
                
    except websockets.exceptions.ConnectionRefused:
        logger.error(f"Could not connect to client {client_id} WebSocket server")
        raise Exception(f"Client {client_id} is not reachable via WebSocket")
    except asyncio.TimeoutError:
        logger.error(f"Timeout connecting to client {client_id}")
        raise Exception(f"Timeout connecting to client {client_id}")
    except Exception as e:
        logger.error(f"WebSocket command execution failed: {e}")
        raise Exception(f"Command execution failed: {str(e)}")