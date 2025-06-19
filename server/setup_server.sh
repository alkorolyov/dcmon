#!/bin/bash
# setup_server.sh - Setup lightweight monitoring server

set -e

SERVER_DIR="/opt/monitoring"
SERVICE_NAME="monitoring-server"

echo "Setting up lightweight monitoring server..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root" >&2
    exit 1
fi

# Install Python and dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv

# Create monitoring user
if ! id "monitoring" &>/dev/null; then
    echo "Creating monitoring user..."
    useradd -r -s /bin/false -d "$SERVER_DIR" monitoring
fi

# Create server directory
echo "Creating server directory..."
mkdir -p "$SERVER_DIR"
cd "$SERVER_DIR"

# Create virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install fastapi uvicorn aiohttp

# Create the main server file (copy your main.py here)
echo "Creating server application..."
cat > main.py << 'EOF'
# Copy the content from the main.py artifact above
EOF

# Create systemd service
echo "Creating systemd service..."
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=Lightweight Monitoring Server
After=network.target

[Service]
Type=simple
User=monitoring
Group=monitoring
WorkingDirectory=$SERVER_DIR
Environment=PATH=$SERVER_DIR/venv/bin
ExecStart=$SERVER_DIR/venv/bin/python main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Set ownership
chown -R monitoring:monitoring "$SERVER_DIR"

# Enable and start service
echo "Starting monitoring server..."
systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl start $SERVICE_NAME

# Setup SSH user for tunnels
if ! id "monitoring" &>/dev/null; then
    echo "Setting up SSH access for monitoring user..."
    mkdir -p /home/monitoring/.ssh
    chmod 700 /home/monitoring/.ssh
    touch /home/monitoring/.ssh/authorized_keys
    chmod 600 /home/monitoring/.ssh/authorized_keys
    chown -R monitoring:monitoring /home/monitoring/.ssh
fi

echo "Setup complete!"
echo ""
echo "Server is running on port 8000"
echo "Dashboard: http://localhost:8000/dashboard"
echo "API docs: http://localhost:8000/docs"
echo ""
echo "To add client SSH keys, append them to: /home/monitoring/.ssh/authorized_keys"
echo ""
echo "Service commands:"
echo "  systemctl status $SERVICE_NAME"
echo "  systemctl restart $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f"