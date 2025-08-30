#!/usr/bin/env python3
"""
dcmon Client - Datacenter Monitoring Client
Collects system metrics and sends them to dcmon server
"""

import asyncio
import aiohttp
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import asdict

from client.exporters import OSMetricsExporter, IpmiExporter, AptExporter, NvmeExporter, NvsmiExporter, MetricPoint
from client.fans import FanController

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('dcmon-client')


class DCMonClient:
    """Main dcmon client application"""
    
    def __init__(self, config_file: str = "/etc/dcmon/config.json"):
        self.config = self._load_config(config_file)
        self.machine_id = self._get_machine_id()
        self.api_key = self._load_api_key()
        self.session = None
        self.fan_controller = None
        self.command_check_counter = 0
        
        # Initialize collectors
        self.collectors = [
            OSMetricsExporter(),
        ]
        
        # Add optional exporters based on availability
        self._init_exporters()
        
        # Initialize fan controller if IPMI is available
        if self.config["exporters"].get("ipmi", False):
            self.fan_controller = FanController()
        
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """Load configuration from file"""
        default_config = {
            "server_url": "https://localhost:8000",
            "collection_interval": 30,
            "exporters": {
                "ipmi": True,
                "apt": True,
                "nvme": True,
                "nvsmi": True
            }
        }
        
        try:
            with open(config_file, 'r') as f:
                user_config = json.load(f)
                default_config.update(user_config)
        except FileNotFoundError:
            logger.info(f"Config file not found: {config_file}, using defaults")
        except Exception as e:
            logger.error(f"Failed to load config: {e}, using defaults")
            
        return default_config
    
    def _get_machine_id(self) -> str:
        """Get unique machine identifier"""
        try:
            with open('/etc/machine-id', 'r') as f:
                return f.read().strip()
        except:
            # Fallback to hardware UUID
            return str(uuid.getnode())
    
    def _load_api_key(self) -> str:
        """Load API key from file"""
        key_file = Path("/etc/dcmon/api_key")
        if key_file.exists():
            return key_file.read_text().strip()
        else:
            raise FileNotFoundError("API key not found. Please register client first.")
    
    def _init_exporters(self):
        """Initialize optional exporters based on configuration"""
        exporter_classes = {
            "ipmi": IpmiExporter,
            "apt": AptExporter,
            "nvme": NvmeExporter,
            "nvsmi": NvsmiExporter,
        }
        
        for name, enabled in self.config["exporters"].items():
            if enabled and name in exporter_classes:
                try:
                    exporter = exporter_classes[name](logger=logger)
                    self.collectors.append(exporter)
                    logger.info(f"Enabled {name} exporter")
                except Exception as e:
                    logger.error(f"Failed to initialize {name} exporter: {e}")
    
    async def start(self):
        """Start the client"""
        logger.info(f"Starting dcmon client (machine_id: {self.machine_id})")
        
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=aiohttp.ClientTimeout(total=30)
        )
        
        # Start main loop
        await self._main_loop()
    
    async def stop(self):
        """Stop the client"""
        if self.session:
            await self.session.close()
            
    async def _main_loop(self):
        """Main collection and transmission loop"""
        while True:
            try:
                # Collect metrics from all collectors
                all_metrics = []
                
                for collector in self.collectors:
                    metrics = await collector.safe_collect()
                    all_metrics.extend(metrics)
                
                logger.info(f"Collected {len(all_metrics)} total metrics")
                
                # Send metrics to server
                if all_metrics:
                    await self._send_metrics(all_metrics)
                
                # Check for commands every 3rd cycle (every ~90s if interval is 30s)
                self.command_check_counter += 1
                if self.command_check_counter >= 3:
                    await self._check_for_commands()
                    self.command_check_counter = 0
                
            except Exception as e:
                logger.error(f"Main loop error: {e}")
            
            # Wait for next collection interval
            await asyncio.sleep(self.config["collection_interval"])
    
    async def _send_metrics(self, metrics: List[MetricPoint]):
        """Send metrics to server"""
        try:
            # Convert metrics to simple dict format
            metrics_data = []
            for metric in metrics:
                metric_dict = asdict(metric)
                metrics_data.append(metric_dict)
            
            payload = {
                "machine_id": self.machine_id,
                "timestamp": int(time.time()),
                "metrics": metrics_data
            }
            
            async with self.session.post(
                f"{self.config['server_url']}/api/metrics",
                json=payload
            ) as response:
                if response.status == 200:
                    logger.debug("Metrics sent successfully")
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to send metrics: {response.status} - {error_text}")
                    
        except Exception as e:
            logger.error(f"Failed to send metrics: {e}")
    
    async def _check_for_commands(self):
        """Check server for pending commands"""
        try:
            async with self.session.get(
                f"{self.config['server_url']}/api/commands/{self.machine_id}"
            ) as response:
                if response.status == 200:
                    commands = await response.json()
                    for command in commands:
                        await self._execute_command(command)
                elif response.status != 404:  # 404 means no commands pending
                    logger.warning(f"Command check failed: {response.status}")
                    
        except Exception as e:
            logger.error(f"Failed to check for commands: {e}")
    
    async def _execute_command(self, command: Dict[str, Any]):
        """Execute a command received from server"""
        try:
            cmd_type = command.get('type')
            cmd_id = command.get('id')
            
            logger.info(f"Executing command {cmd_id}: {cmd_type}")
            
            result = {'success': False, 'message': 'Unknown command type'}
            
            if cmd_type == 'fan_control' and self.fan_controller:
                result = await self.fan_controller.execute_fan_command(command.get('params', {}))
            elif cmd_type == 'reboot':
                result = await self._execute_reboot_command(command.get('params', {}))
            elif cmd_type == 'config_update':
                result = await self._execute_config_update(command.get('params', {}))
            else:
                result['message'] = f'Unsupported command type: {cmd_type}'
            
            # Send command result back to server
            await self._send_command_result(cmd_id, result)
            
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            if 'cmd_id' in locals():
                await self._send_command_result(cmd_id, {
                    'success': False, 
                    'message': f'Command execution error: {e}'
                })
    
    async def _execute_reboot_command(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute reboot command"""
        delay = params.get('delay', 60)  # Default 60 second delay
        
        try:
            # Schedule reboot
            import subprocess
            subprocess.run(['shutdown', '-r', f'+{delay//60}'], check=True)
            return {
                'success': True, 
                'message': f'Reboot scheduled in {delay} seconds'
            }
        except Exception as e:
            return {
                'success': False, 
                'message': f'Failed to schedule reboot: {e}'
            }
    
    async def _execute_config_update(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute configuration update"""
        try:
            # Update in-memory config
            if 'collection_interval' in params:
                self.config['collection_interval'] = params['collection_interval']
            
            if 'exporters' in params:
                self.config['exporters'].update(params['exporters'])
            
            return {
                'success': True, 
                'message': 'Configuration updated successfully'
            }
        except Exception as e:
            return {
                'success': False, 
                'message': f'Config update failed: {e}'
            }
    
    async def _send_command_result(self, command_id: str, result: Dict[str, Any]):
        """Send command execution result back to server"""
        try:
            payload = {
                'machine_id': self.machine_id,
                'command_id': command_id,
                'timestamp': int(time.time()),
                'result': result
            }
            
            async with self.session.post(
                f"{self.config['server_url']}/api/command-results",
                json=payload
            ) as response:
                if response.status != 200:
                    logger.warning(f"Failed to send command result: {response.status}")
                    
        except Exception as e:
            logger.error(f"Failed to send command result: {e}")

async def main():
    """Main entry point"""
    client = DCMonClient()
    
    try:
        await client.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await client.stop()

if __name__ == "__main__":
    asyncio.run(main())