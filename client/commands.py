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


async def start_websocket_command_client(config, client_id: int, client_token: str):
    """Connect to server's WebSocket endpoint for handling commands."""
    handler = WebSocketCommandHandler(config)

    # Parse server URL to construct WebSocket URL
    server_url = config.server.rstrip("/")
    # Convert http(s):// to ws(s)://
    ws_url = server_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_endpoint = f"{ws_url}/ws/client/{client_id}"

    logger.info(f"Connecting to WebSocket command endpoint: {ws_endpoint}")

    # Reconnection loop
    while True:
        try:
            # Connect to server's WebSocket endpoint
            async with websockets.connect(ws_endpoint, ssl=_create_ssl_context()) as websocket:
                logger.info(f"Connected to server WebSocket for commands")

                # Listen for commands from server
                while True:
                    try:
                        # Wait for command from server
                        message = await websocket.recv()
                        command_data = json.loads(message)

                        command_type = command_data.get("command_type")
                        command_payload = command_data.get("command_data", {})

                        logger.info(f"Received command: {command_type}")

                        # Execute command
                        result = await handler.handle_command(command_type, command_payload)

                        # Send result back
                        await websocket.send(json.dumps({
                            "status": "completed",
                            "result": result
                        }))

                        logger.info(f"Command {command_type} completed successfully")

                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("WebSocket connection closed by server")
                        break
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON received: {e}")
                    except Exception as e:
                        logger.error(f"Error handling command: {e}")
                        try:
                            await websocket.send(json.dumps({
                                "status": "error",
                                "error": str(e)
                            }))
                        except:
                            pass

        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            logger.info("Reconnecting in 10 seconds...")
            await asyncio.sleep(10)


def _create_ssl_context():
    """Create SSL context that trusts self-signed certificates."""
    import ssl
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return ssl_context