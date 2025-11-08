#!/usr/bin/env python3
"""
WebSocket Command Handler for dcmon Client

Handles real-time command execution via WebSocket connections from the server.
Integrates with existing command handlers (fans.py, etc.)
"""

import asyncio
import json
import logging
import websockets
from typing import Dict, Any, Optional
from pathlib import Path

# Import existing command handlers
try:
    from .fans import FanController
except ImportError:
    from fans import FanController

logger = logging.getLogger(__name__)


class WebSocketCommandHandler:
    """Handles WebSocket connections for real-time command execution."""
    
    def __init__(self, config):
        self.config = config
        self.fan_controller = FanController()
        self.logger = logging.getLogger(__name__)
        
    async def handle_command(self, command_type: str, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute command and return result."""
        try:
            if command_type == "fan_control":
                # Use existing fan controller
                result = await self.fan_controller.execute_fan_command(command_data)
                return result
                
            elif command_type == "ipmi_raw":
                # Execute raw IPMI command
                return await self._execute_ipmi_raw(command_data)
                
            elif command_type == "system_info":
                # Get system information
                return await self._get_system_info(command_data)
                
            else:
                return {
                    "success": False,
                    "message": f"Unknown command type: {command_type}"
                }
                
        except Exception as e:
            self.logger.error(f"Command execution failed: {e}")
            return {
                "success": False,
                "message": f"Command execution error: {str(e)}"
            }
    
    async def _execute_ipmi_raw(self, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute raw IPMI command."""
        raw_command = command_data.get("raw_command", "")
        if not raw_command:
            return {"success": False, "message": "No raw_command provided"}
            
        try:
            # Execute IPMI raw command using ipmitool
            cmd = ['ipmitool', 'raw'] + raw_command.split()
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return {
                    "success": True,
                    "result": stdout.decode().strip(),
                    "command": raw_command
                }
            else:
                return {
                    "success": False,
                    "message": f"IPMI command failed: {stderr.decode().strip()}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"IPMI execution error: {str(e)}"
            }
    
    async def _get_system_info(self, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """Get system information."""
        info_type = command_data.get("info_type", "basic")
        
        try:
            if info_type == "basic":
                # Get basic system info
                import platform
                import psutil
                
                return {
                    "success": True,
                    "result": {
                        "hostname": platform.node(),
                        "platform": platform.platform(),
                        "cpu_count": psutil.cpu_count(),
                        "memory_total": psutil.virtual_memory().total,
                        "disk_usage": dict(psutil.disk_usage('/'))
                    }
                }
            else:
                return {
                    "success": False,
                    "message": f"Unknown info_type: {info_type}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"System info error: {str(e)}"
            }


async def start_websocket_command_server(config, client_id: int, client_token: str):
    """Start WebSocket server for handling commands from dcmon server."""
    handler = WebSocketCommandHandler(config)
    
    # Use WebSocket port from config
    websocket_port = config.websocket_port
    
    logger.info(f"Starting WebSocket command server on port {websocket_port}")
    
    async def handle_websocket(websocket, path):
        """Handle incoming WebSocket connections from server."""
        try:
            logger.info(f"WebSocket command connection established from {websocket.remote_address}")
            
            # Authenticate using client token
            auth_message = await websocket.recv()
            auth_data = json.loads(auth_message)
            
            if auth_data.get("client_token") != client_token:
                await websocket.send(json.dumps({"error": "Authentication failed"}))
                return
                
            await websocket.send(json.dumps({"status": "authenticated"}))
            
            # Wait for command
            command_message = await websocket.recv()
            command_data = json.loads(command_message)
            
            command_type = command_data.get("command_type")
            command_payload = command_data.get("command_data", {})
            
            logger.info(f"Executing command: {command_type}")
            
            # Execute command
            result = await handler.handle_command(command_type, command_payload)
            
            # Send result back
            await websocket.send(json.dumps({
                "status": "completed",
                "result": result
            }))
            
            logger.info(f"Command {command_type} completed successfully")
            
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error(f"WebSocket command error: {e}")
            try:
                await websocket.send(json.dumps({
                    "status": "error",
                    "error": str(e)
                }))
            except:
                pass
    
    # Start WebSocket server
    try:
        await websockets.serve(handle_websocket, "0.0.0.0", websocket_port)
        logger.info(f"WebSocket command server started on port {websocket_port}")
        
        # Keep running
        await asyncio.Future()  # Run forever
        
    except Exception as e:
        logger.error(f"Failed to start WebSocket command server: {e}")
        raise