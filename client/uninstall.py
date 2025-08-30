#!/usr/bin/env python3
"""
dcmon Client Uninstaller
Removes systemd service, configuration files, and application directories
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def check_root():
    """Check if running as root"""
    if os.geteuid() != 0:
        print("This uninstaller must be run as root (sudo)")
        sys.exit(1)

def stop_and_disable_service():
    """Stop and disable the dcmon-client service"""
    service_name = "dcmon-client"
    
    try:
        # Stop the service
        result = subprocess.run(["systemctl", "stop", service_name], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✓ Stopped {service_name} service")
        else:
            print(f"⚠ Service {service_name} was not running")
        
        # Disable the service
        result = subprocess.run(["systemctl", "disable", service_name], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✓ Disabled {service_name} service")
        else:
            print(f"⚠ Service {service_name} was not enabled")
            
    except Exception as e:
        print(f"⚠ Error managing service: {e}")

def remove_systemd_service():
    """Remove systemd service file"""
    service_path = Path("/etc/systemd/system/dcmon-client.service")
    
    try:
        if service_path.exists():
            service_path.unlink()
            print("✓ Removed systemd service file")
            
            # Reload systemd daemon
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            print("✓ Reloaded systemd daemon")
        else:
            print("⚠ Systemd service file not found")
    except Exception as e:
        print(f"✗ Error removing service file: {e}")

def remove_application_files():
    """Remove application directory"""
    app_dir = Path("/opt/dcmon")
    
    try:
        if app_dir.exists():
            shutil.rmtree(app_dir)
            print("✓ Removed application directory (/opt/dcmon)")
        else:
            print("⚠ Application directory not found")
    except Exception as e:
        print(f"✗ Error removing application directory: {e}")

def remove_config_and_logs(preserve_config=False):
    """Remove configuration and log directories"""
    config_dir = Path("/etc/dcmon")
    log_dir = Path("/var/log/dcmon")
    
    # Handle configuration directory
    try:
        if config_dir.exists():
            if preserve_config:
                print(f"⚠ Preserving configuration directory: {config_dir}")
            else:
                shutil.rmtree(config_dir)
                print("✓ Removed configuration directory (/etc/dcmon)")
        else:
            print("⚠ Configuration directory not found")
    except Exception as e:
        print(f"✗ Error removing configuration directory: {e}")
    
    # Handle log directory
    try:
        if log_dir.exists():
            if preserve_config:
                print(f"⚠ Preserving log directory: {log_dir}")
            else:
                shutil.rmtree(log_dir)
                print("✓ Removed log directory (/var/log/dcmon)")
        else:
            print("⚠ Log directory not found")
    except Exception as e:
        print(f"✗ Error removing log directory: {e}")

def main():
    """Main uninstall process"""
    print("dcmon Client Uninstaller")
    print("=" * 40)
    
    # Check if running as root
    check_root()
    
    # Ask about preserving config/logs
    preserve = input("Preserve configuration and logs? (y/N): ").lower().strip()
    preserve_config = preserve in ['y', 'yes']
    
    if not preserve_config:
        confirm = input("This will completely remove dcmon client. Continue? (y/N): ").lower().strip()
        if confirm not in ['y', 'yes']:
            print("Uninstall cancelled.")
            sys.exit(0)
    
    print("\nUninstalling dcmon client...")
    
    # Step 1: Stop and disable service
    stop_and_disable_service()
    
    # Step 2: Remove systemd service file
    remove_systemd_service()
    
    # Step 3: Remove application files
    remove_application_files()
    
    # Step 4: Remove config and logs (optionally preserve)
    remove_config_and_logs(preserve_config)
    
    print("\n" + "=" * 40)
    if preserve_config:
        print("✓ dcmon client uninstalled (config/logs preserved)")
        print("  Configuration: /etc/dcmon")
        print("  Logs: /var/log/dcmon")
    else:
        print("✓ dcmon client completely removed")
    
    print("\nNote: Python dependencies (aiohttp) were not removed")
    print("      Run 'pip uninstall aiohttp' if no longer needed")

if __name__ == "__main__":
    main()