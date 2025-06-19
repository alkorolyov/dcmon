#!/bin/bash
# uninstall_server.sh - Remove lightweight monitoring server

set -e

SERVER_DIR="/opt/monitoring"
SERVICE_NAME="monitoring-server"
MONITORING_USER="monitoring"

echo "Uninstalling lightweight monitoring server..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root" >&2
    exit 1
fi

# Confirmation prompt
read -p "This will completely remove the monitoring server and all data. Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Uninstall cancelled."
    exit 0
fi

echo "=> Stopping and disabling monitoring service..."
if systemctl is-active --quiet $SERVICE_NAME; then
    systemctl stop $SERVICE_NAME
    echo "Service stopped."
fi

if systemctl is-enabled --quiet $SERVICE_NAME 2>/dev/null; then
    systemctl disable $SERVICE_NAME
    echo "Service disabled."
fi

echo "=> Removing systemd service file..."
if [ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]; then
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    systemctl daemon-reload
    echo "Service file removed."
fi

echo "=> Removing server directory and data..."
if [ -d "$SERVER_DIR" ]; then
    rm -rf "$SERVER_DIR"
    echo "Server directory removed: $SERVER_DIR"
fi

echo "=> Cleaning up monitoring user..."
if id "$MONITORING_USER" &>/dev/null; then
    # Stop any processes running as monitoring user
    pkill -u "$MONITORING_USER" || true

    # Remove user and home directory
    userdel -r "$MONITORING_USER" 2>/dev/null || true
    echo "Monitoring user removed."
fi

echo "=> Cleaning up SSH configuration..."
# Remove any SSH configurations that might have been set up
if [ -d "/home/$MONITORING_USER" ]; then
    rm -rf "/home/$MONITORING_USER"
fi

echo "=> Removing Python packages (optional)..."
read -p "Remove Python packages (fastapi, uvicorn, aiohttp)? This might affect other applications. (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    pip3 uninstall -y fastapi uvicorn aiohttp 2>/dev/null || true
    echo "Python packages removed."
fi

echo "=> Cleaning up system packages (optional)..."
read -p "Remove system packages (python3-pip, python3-venv)? This might affect other applications. (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    apt-get remove --purge -y python3-pip python3-venv 2>/dev/null || true
    apt-get autoremove -y 2>/dev/null || true
    echo "System packages removed."
fi

echo "=> Checking for any remaining processes..."
# Kill any remaining processes that might be using the old paths
pkill -f "monitoring" || true
pkill -f "$SERVER_DIR" || true

echo "=> Verifying removal..."
# Check if service still exists
if systemctl list-units --full -all | grep -q "$SERVICE_NAME"; then
    echo "WARNING: Service may still be present in systemd"
fi

# Check if directory still exists
if [ -d "$SERVER_DIR" ]; then
    echo "WARNING: Server directory still exists: $SERVER_DIR"
fi

# Check if user still exists
if id "$MONITORING_USER" &>/dev/null; then
    echo "WARNING: Monitoring user still exists"
fi

echo ""
echo "=== Uninstall Summary ==="
echo "✓ Monitoring service stopped and disabled"
echo "✓ Service files removed"
echo "✓ Server directory removed: $SERVER_DIR"
echo "✓ Monitoring user removed"
echo "✓ SSH configurations cleaned up"
echo ""
echo "Uninstall complete!"
echo ""
echo "Note: Any SSH tunnels from clients will fail to connect."
echo "You may want to uninstall the client components as well."