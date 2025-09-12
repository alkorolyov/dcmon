#!/usr/bin/env python3
"""
Secure WebSocket Command Client for dcmon

Client connects TO server for command reception (not the reverse).
No open ports on client machine - much more secure!
"""

import asyncio
import json
import logging
import ssl
import websockets
from typing import Dict, Any, Optional
from pathlib import Path

# Import existing command handlers
try:
    from .fans import FanController
    from .utils import create_ssl_context
except ImportError:
    from fans import FanController
    from utils import create_ssl_context

logger = logging.getLogger(__name__)


class SecureWebSocketCommandClient:
    """Secure WebSocket client that connects to server for command reception."""
    
    def __init__(self, config, client_id: int, client_token: str):
        self.config = config
        self.client_id = client_id
        self.client_token = client_token
        self.fan_controller = FanController()
        self.logger = logging.getLogger(__name__)
        self.reconnect_delay = 5  # seconds
        self.max_reconnect_delay = 60  # seconds
        
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
        info_type = command_data.get("type", "basic")
        
        try:
            if info_type == "basic":
                # Get basic system info
                import platform
                import psutil
                
                disk_usage = psutil.disk_usage('/')
                return {
                    "success": True,
                    "result": {
                        "hostname": platform.node(),
                        "platform": platform.platform(),
                        "cpu_count": psutil.cpu_count(),
                        "memory_total": psutil.virtual_memory().total,
                        "disk_usage": {
                            "total": disk_usage.total,
                            "used": disk_usage.used,
                            "free": disk_usage.free
                        }
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

    async def connect_and_listen(self):
        """Connect to server WebSocket and listen for commands."""
        # Convert server URL to WebSocket URL
        server_url = self.config.server.replace("https://", "wss://").replace("http://", "ws://")
        websocket_url = f"{server_url}/ws/client/{self.client_id}"
        
        current_delay = self.reconnect_delay
        
        while True:
            try:
                logger.info(f"Connecting to server WebSocket: {websocket_url}")
                
                # Connect to server WebSocket with timeout
                # Use SSL context for WSS URLs to auto-trust self-signed certificates
                ssl_context = create_ssl_context() if websocket_url.startswith("wss://") else None
                websocket = await asyncio.wait_for(
                    websockets.connect(
                        websocket_url,
                        ssl=ssl_context,
                        ping_interval=30,
                        ping_timeout=10
                    ),
                    timeout=10
                )
                
                async with websocket:
                    logger.info(f"Connected to server WebSocket for commands")
                    current_delay = self.reconnect_delay  # Reset delay on successful connection
                    
                    # Send authentication (if needed in future)
                    # await websocket.send(json.dumps({"client_token": self.client_token}))
                    
                    # Listen for commands
                    while True:
                        try:
                            # Receive command from server
                            message = await websocket.recv()
                            command_data = json.loads(message)
                            
                            command_type = command_data.get("command_type")
                            command_payload = command_data.get("command_data", {})
                            
                            if command_type:
                                logger.info(f"Received command: {command_type}")
                                
                                # Execute command
                                result = await self.handle_command(command_type, command_payload)
                                
                                # Send result back to server
                                await websocket.send(json.dumps({
                                    "result": result
                                }))
                                
                                logger.info(f"Command {command_type} completed and result sent")
                            else:
                                # Keep-alive or other message - just acknowledge
                                logger.debug(f"Received keep-alive message: {command_data}")
                                # Don't send anything back to avoid message conflicts
                                
                        except websockets.exceptions.ConnectionClosed:
                            logger.warning("WebSocket connection closed by server")
                            break
                        except json.JSONDecodeError as e:
                            logger.error(f"Invalid JSON received: {e}")
                        except Exception as e:
                            logger.error(f"Error processing command: {e}")
                            # Try to send error back to server
                            try:
                                await websocket.send(json.dumps({
                                    "result": {
                                        "success": False,
                                        "message": f"Command processing error: {str(e)}"
                                    }
                                }))
                            except:
                                pass
                            
            except (websockets.exceptions.ConnectionClosedError, 
                    websockets.exceptions.InvalidURI,
                    ConnectionRefusedError,
                    OSError) as e:
                logger.warning(f"WebSocket connection failed: {e}")
                logger.info(f"Retrying WebSocket connection in {current_delay} seconds...")
                await asyncio.sleep(current_delay)
                # Exponential backoff
                current_delay = min(current_delay * 2, self.max_reconnect_delay)
                
            except Exception as e:
                logger.error(f"Unexpected WebSocket error: {e}")
                await asyncio.sleep(current_delay)
                current_delay = min(current_delay * 2, self.max_reconnect_delay)


async def start_secure_websocket_command_client(config, client_id: int, client_token: str):
    """Start secure WebSocket command client (connects TO server)."""
    client = SecureWebSocketCommandClient(config, client_id, client_token)
    
    logger.info(f"Starting secure WebSocket command client (client {client_id})")
    
    try:
        await client.connect_and_listen()
    except Exception as e:
        logger.error(f"WebSocket command client failed: {e}")
        raise