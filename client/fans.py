#!/usr/bin/env python3
"""
Fan Control Module for dcmon Client
Handles IPMI fan speed control and BMC mode management

Compatibility:
- Supermicro H11 series motherboards (AMD EPYC)
- Supermicro H12 series motherboards (AMD EPYC)  
- Supermicro X11 series motherboards (Intel Xeon)
- Supermicro X12 series motherboards (Intel Xeon)

Requirements:
- ipmitool package installed
- IPMI interface configured and accessible
- Root privileges for IPMI raw commands

IPMI Commands Used:
- 0x30 0x45 0x00/0x01 - Get/Set BMC fan mode
- 0x30 0x70 0x66 0x00/0x01 - Get/Set fan zone speeds

Note: Other Supermicro series may work but are untested.
"""

import subprocess
import asyncio
import logging
from typing import Dict, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)

class BMCFanMode(Enum):
    """BMC Fan Control Modes"""
    STANDARD = 0x00  # Auto
    FULL_SPEED = 0x01
    OPTIMAL = 0x02
    HEAVY_IO = 0x04

class FanController:
    """IPMI Fan Controller"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def run_ipmi_command(self, *args) -> Optional[str]:
        """Run IPMI command and return output"""
        try:
            cmd = ['ipmitool', 'raw'] + list(args)
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0:
                self.logger.error(f"IPMI command failed: {stderr.decode()}")
                return None
                
            return stdout.decode().strip()
            
        except Exception as e:
            self.logger.error(f"Failed to run IPMI command: {e}")
            return None
    
    async def get_bmc_fan_mode(self) -> Optional[BMCFanMode]:
        """Get current BMC fan mode"""
        result = await self.run_ipmi_command('0x30', '0x45', '0x00')
        if not result:
            return None
            
        try:
            # Clean hex output
            clean_hex = result.replace(' ', '').strip()
            mode_value = int(clean_hex, 16)
            
            # Map to enum
            for mode in BMCFanMode:
                if mode.value == mode_value:
                    return mode
                    
            self.logger.warning(f"Unknown BMC fan mode: {mode_value}")
            return None
            
        except ValueError as e:
            self.logger.error(f"Failed to parse BMC mode: {e}")
            return None
    
    async def set_bmc_fan_mode(self, mode: BMCFanMode) -> bool:
        """Set BMC fan mode"""
        result = await self.run_ipmi_command('0x30', '0x45', '0x01', f'0x{mode.value:02x}')
        return result is not None
    
    async def get_fan_speeds(self) -> Dict[int, Optional[int]]:
        """Get current fan speeds for both zones"""
        speeds = {}
        
        for zone in [0, 1]:
            result = await self.run_ipmi_command('0x30', '0x70', '0x66', '0x00', str(zone))
            if result:
                try:
                    clean_hex = result.replace(' ', '').strip()
                    speeds[zone] = int(clean_hex, 16)
                except ValueError:
                    speeds[zone] = None
            else:
                speeds[zone] = None
                
        return speeds
    
    async def set_fan_speed(self, zone: int, speed_percent: int) -> bool:
        """Set fan speed for specific zone (0-100%)"""
        if not (0 <= speed_percent <= 100):
            self.logger.error(f"Invalid speed: {speed_percent}%. Must be 0-100")
            return False
            
        if zone not in [0, 1]:
            self.logger.error(f"Invalid zone: {zone}. Must be 0 or 1")
            return False
        
        speed_hex = f'0x{speed_percent:02x}'
        result = await self.run_ipmi_command('0x30', '0x70', '0x66', '0x01', str(zone), speed_hex)
        return result is not None
    
    async def set_fan_speeds(self, zone0_speed: int, zone1_speed: int) -> Tuple[bool, bool]:
        """Set fan speeds for both zones"""
        results = await asyncio.gather(
            self.set_fan_speed(0, zone0_speed),
            self.set_fan_speed(1, zone1_speed),
            return_exceptions=True
        )
        
        return (
            results[0] if isinstance(results[0], bool) else False,
            results[1] if isinstance(results[1], bool) else False
        )
    
    async def get_fan_status(self) -> Dict:
        """Get complete fan status including BMC mode and speeds"""
        bmc_mode = await self.get_bmc_fan_mode()
        fan_speeds = await self.get_fan_speeds()
        
        return {
            'bmc_mode': bmc_mode.name if bmc_mode else None,
            'bmc_mode_value': bmc_mode.value if bmc_mode else None,
            'zone_0_speed': fan_speeds.get(0),
            'zone_1_speed': fan_speeds.get(1),
        }
    
    async def execute_fan_command(self, command: Dict) -> Dict:
        """Execute fan control command from server"""
        cmd_type = command.get('action')
        result = {'success': False, 'message': ''}
        
        try:
            if cmd_type == 'get_status':
                status = await self.get_fan_status()
                result = {'success': True, 'data': status}
                
            elif cmd_type == 'set_bmc_mode':
                mode_name = command.get('mode', '').upper()
                try:
                    mode = BMCFanMode[mode_name]
                    success = await self.set_bmc_fan_mode(mode)
                    result = {
                        'success': success,
                        'message': f'BMC mode set to {mode_name}' if success else 'Failed to set BMC mode'
                    }
                except KeyError:
                    result['message'] = f'Invalid BMC mode: {mode_name}'
                    
            elif cmd_type == 'set_fan_speed':
                zone = command.get('zone')
                speed = command.get('speed')
                
                if zone is not None and speed is not None:
                    success = await self.set_fan_speed(zone, speed)
                    result = {
                        'success': success,
                        'message': f'Zone {zone} speed set to {speed}%' if success else f'Failed to set zone {zone} speed'
                    }
                else:
                    result['message'] = 'Missing zone or speed parameter'
                    
            elif cmd_type == 'set_fan_speeds':
                zone0_speed = command.get('zone0_speed')
                zone1_speed = command.get('zone1_speed')
                
                if zone0_speed is not None and zone1_speed is not None:
                    success0, success1 = await self.set_fan_speeds(zone0_speed, zone1_speed)
                    result = {
                        'success': success0 and success1,
                        'message': f'Zone 0: {"OK" if success0 else "FAIL"}, Zone 1: {"OK" if success1 else "FAIL"}'
                    }
                else:
                    result['message'] = 'Missing zone0_speed or zone1_speed parameter'
                    
            else:
                result['message'] = f'Unknown fan command: {cmd_type}'
                
        except Exception as e:
            result['message'] = f'Fan command error: {e}'
            self.logger.error(f"Fan command execution failed: {e}")
            
        return result

# CLI interface for standalone usage
async def main():
    """CLI interface for testing"""
    import sys
    
    controller = FanController()
    
    if len(sys.argv) == 1:
        # Show status
        status = await controller.get_fan_status()
        print(f"BMC Mode: {status['bmc_mode']} ({status['bmc_mode_value']})")
        print(f"Zone 0 fan speed: {status['zone_0_speed']}%")
        print(f"Zone 1 fan speed: {status['zone_1_speed']}%")
        
    elif len(sys.argv) == 2:
        # Set both zones to same speed
        try:
            speed = int(sys.argv[1])
            if 0 <= speed <= 100:
                success0, success1 = await controller.set_fan_speeds(speed, speed)
                if success0 and success1:
                    print(f"Fan speed set to {speed}% for both zones")
                else:
                    print("Failed to set fan speeds")
                    sys.exit(1)
            else:
                print("Speed must be between 0-100")
                sys.exit(1)
        except ValueError:
            print("Invalid speed value")
            sys.exit(1)
    
    else:
        print("Usage: fans.py [speed_0_to_100]")
        sys.exit(1)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())