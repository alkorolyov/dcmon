#!/bin/bash
# ssh_tunnel.sh - Create SSH tunnel for node_exporter

# Configuration
SERVER_HOST="your-server.com"
SERVER_USER="monitoring"
SSH_PORT="22"
LOCAL_PORT="9100"  # node_exporter port
REMOTE_PORT_BASE="19100"  # Base port on server (will add machine ID offset)

# Get unique machine identifier
MACHINE_ID=$(hostname | tr -cd '[:alnum:]' | tail -c 8)
MACHINE_ID_NUM=$(echo "$MACHINE_ID" | od -An -N4 -tx4 | tr -d ' ' | head -c 4)
MACHINE_ID_NUM=$((0x$MACHINE_ID_NUM % 1000))  # Convert to number 0-999

REMOTE_PORT=$((REMOTE_PORT_BASE + MACHINE_ID_NUM))

# SSH key path (create if doesn't exist)
SSH_KEY="/etc/ssh/monitoring_key"

# Function to generate SSH key if it doesn't exist
setup_ssh_key() {
    if [ ! -f "$SSH_KEY" ]; then
        echo "Generating SSH key for monitoring..."
        ssh-keygen -t rsa -b 2048 -f "$SSH_KEY" -N "" -C "monitoring-$(hostname)"
        echo "SSH key generated. Please add the following public key to the server:"
        echo "---"
        cat "${SSH_KEY}.pub"
        echo "---"
        echo "Add this to ~/.ssh/authorized_keys on the server for user $SERVER_USER"
        read -p "Press Enter when you've added the key to the server..."
    fi
}

# Function to create systemd service for persistent tunnel
create_tunnel_service() {
    SERVICE_FILE="/etc/systemd/system/ssh-tunnel-monitoring.service"

    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=SSH Tunnel for Node Exporter Monitoring
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/ssh -N -T -o ServerAliveInterval=60 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=no -i $SSH_KEY -R $REMOTE_PORT:localhost:$LOCAL_PORT $SERVER_USER@$SERVER_HOST -p $SSH_PORT
Restart=always
RestartSec=5
StartLimitInterval=0

[Install]
WantedBy=multi-user.target
EOF

    echo "Created systemd service: $SERVICE_FILE"
}

# Function to start tunnel service
start_tunnel() {
    systemctl daemon-reload
    systemctl enable ssh-tunnel-monitoring
    systemctl start ssh-tunnel-monitoring

    echo "SSH tunnel service started and enabled"
    echo "This machine will be accessible on server port: $REMOTE_PORT"
    echo "Machine ID: $MACHINE_ID (numeric: $MACHINE_ID_NUM)"
}

# Function to show status
show_status() {
    echo "SSH Tunnel Status:"
    systemctl status ssh-tunnel-monitoring --no-pager
    echo ""
    echo "Active tunnels:"
    ss -tlnp | grep ":$LOCAL_PORT"
}

# Main execution
case "${1:-setup}" in
    "setup")
        echo "Setting up SSH tunnel for monitoring..."
        setup_ssh_key
        create_tunnel_service
        start_tunnel
        show_status
        ;;
    "start")
        systemctl start ssh-tunnel-monitoring
        ;;
    "stop")
        systemctl stop ssh-tunnel-monitoring
        ;;
    "restart")
        systemctl restart ssh-tunnel-monitoring
        ;;
    "status")
        show_status
        ;;
    "logs")
        journalctl -u ssh-tunnel-monitoring -f
        ;;
    *)
        echo "Usage: $0 {setup|start|stop|restart|status|logs}"
        echo "  setup  - Initial setup (creates keys, service, and starts tunnel)"
        echo "  start  - Start the tunnel"
        echo "  stop   - Stop the tunnel"
        echo "  restart- Restart the tunnel"
        echo "  status - Show tunnel status"
        echo "  logs   - Show tunnel logs"
        exit 1
        ;;
esac