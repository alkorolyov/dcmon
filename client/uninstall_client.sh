#!/bin/bash
# uninstall_client.sh - Remove monitoring client components

set -e

VAR_DIR='/var/lib/node_exporter'
SSH_KEY="/etc/ssh/monitoring_key"

echo "Uninstalling monitoring client components..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root" >&2
    exit 1
fi

# Confirmation prompt
read -p "This will remove all monitoring client components. Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Uninstall cancelled."
    exit 0
fi

echo "=> Stopping and disabling services..."

# Stop and disable node_exporter service
if systemctl is-active --quiet node_exporter; then
    systemctl stop node_exporter
    echo "node_exporter service stopped."
fi

if systemctl is-enabled --quiet node_exporter 2>/dev/null; then
    systemctl disable node_exporter
    echo "node_exporter service disabled."
fi

# Stop and disable run_exporters service
if systemctl is-active --quiet run_exporters; then
    systemctl stop run_exporters
    echo "run_exporters service stopped."
fi

if systemctl is-enabled --quiet run_exporters 2>/dev/null; then
    systemctl disable run_exporters
    echo "run_exporters service disabled."
fi

# Stop and disable SSH tunnel service
if systemctl is-active --quiet ssh-tunnel-monitoring; then
    systemctl stop ssh-tunnel-monitoring
    echo "SSH tunnel service stopped."
fi

if systemctl is-enabled --quiet ssh-tunnel-monitoring 2>/dev/null; then
    systemctl disable ssh-tunnel-monitoring
    echo "SSH tunnel service disabled."
fi

echo "=> Removing systemd service files..."
service_files=(
    "/etc/systemd/system/node_exporter.service"
    "/etc/systemd/system/run_exporters.service"
    "/etc/systemd/system/ssh-tunnel-monitoring.service"
)

for service_file in "${service_files[@]}"; do
    if [ -f "$service_file" ]; then
        rm -f "$service_file"
        echo "Removed: $service_file"
    fi
done

systemctl daemon-reload
echo "Systemd configuration reloaded."

echo "=> Removing node_exporter directory..."
if [ -d "$VAR_DIR" ]; then
    rm -rf "$VAR_DIR"
    echo "Removed: $VAR_DIR"
fi

echo "=> Removing SSH keys..."
if [ -f "$SSH_KEY" ]; then
    rm -f "$SSH_KEY"
    echo "Removed: $SSH_KEY"
fi

if [ -f "${SSH_KEY}.pub" ]; then
    rm -f "${SSH_KEY}.pub"
    echo "Removed: ${SSH_KEY}.pub"
fi

echo "=> Cleaning up any remaining processes..."
# Kill any processes that might still be running
pkill -f "node_exporter" || true
pkill -f "run_exporters" || true
pkill -f "ssh.*monitoring" || true

echo "=> Removing system packages (optional)..."
read -p "Remove monitoring-related packages (nvme-cli, jq, ipmitool)? These might be used by other applications. (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    apt-get remove --purge -y nvme-cli jq ipmitool 2>/dev/null || true
    echo "Monitoring packages removed."
fi

read -p "Remove git and openssh-client? These are commonly used by other applications. (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    apt-get remove --purge -y git openssh-client 2>/dev/null || true
    echo "Git and SSH client removed."
fi

read -p "Run apt autoremove to clean up unused dependencies? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    apt-get autoremove -y
    echo "Unused dependencies removed."
fi

echo "=> Cleaning up temporary files..."
# Remove any temporary installation files
rm -rf /tmp/dcmon 2>/dev/null || true
rm -rf /tmp/node_exporter* 2>/dev/null || true

echo "=> Verifying removal..."
# Check if services still exist
remaining_services=()
for service in node_exporter run_exporters ssh-tunnel-monitoring; do
    if systemctl list-units --full -all | grep -q "$service"; then
        remaining_services+=("$service")
    fi
done

if [ ${#remaining_services[@]} -gt 0 ]; then
    echo "WARNING: Some services may still be present in systemd:"
    printf "  - %s\n" "${remaining_services[@]}"
fi

# Check if directory still exists
if [ -d "$VAR_DIR" ]; then
    echo "WARNING: Node exporter directory still exists: $VAR_DIR"
fi

# Check if SSH keys still exist
if [ -f "$SSH_KEY" ] || [ -f "${SSH_KEY}.pub" ]; then
    echo "WARNING: SSH keys still exist"
fi

echo ""
echo "=== Uninstall Summary ==="
echo "✓ All monitoring services stopped and disabled"
echo "✓ Service files removed"
echo "✓ Node exporter directory removed: $VAR_DIR"
echo "✓ SSH tunnel configuration removed"
echo "✓ SSH keys removed"
echo "✓ Temporary files cleaned up"
echo ""
echo "Uninstall complete!"
echo ""
echo "Note: This node will no longer send metrics to the monitoring server."

# Optional: Show what processes are still running that might be related
echo ""
echo "Checking for any remaining monitoring-related processes..."
ps aux | grep -E "(node_exporter|ssh.*monitoring|prometheus)" | grep -v grep || echo "No monitoring processes found."