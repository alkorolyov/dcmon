#!/bin/bash
#
# dcmon Client Installer
# Creates systemd service and installs dcmon client
#

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_step() {
    echo -e "${BLUE}$1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This installer must be run as root (sudo)"
        exit 1
    fi
}

create_directories() {
    print_step "Creating directories..."
    
    local dirs=(
        "/etc/dcmon"
        "/opt/dcmon"
        "/var/log/dcmon"
    )
    
    for dir in "${dirs[@]}"; do
        mkdir -p "$dir"
        print_success "Created directory: $dir"
    done
}

install_dependencies() {
    print_step "Installing system dependencies..."
    
    # Update package list
    if apt update >/dev/null 2>&1; then
        print_success "Updated package list"
    else
        print_warning "Failed to update package list"
    fi
    
    # Install Python3 and pip
    if apt install -y python3 python3-pip ipmitool nvme-cli >/dev/null 2>&1; then
        print_success "Installed Python3, pip, ipmitool, and nvme-cli"
    else
        print_error "Failed to install system dependencies"
        return 1
    fi
    
    # Install Python dependencies
    if python3 -m pip install -r "/opt/dcmon/requirements.txt" >/dev/null 2>&1; then
        print_success "Installed Python dependencies"
    else
        print_warning "Failed to install from requirements.txt, installing manually"
        if python3 -m pip install aiohttp asyncio-throttle cryptography >/dev/null 2>&1; then
            print_success "Installed Python dependencies manually"
        else
            print_error "Failed to install Python dependencies"
            return 1
        fi
    fi
    
    return 0
}

install_files() {
    print_step "Installing client files..."
    
    local current_dir="$(dirname "$0")"
    
    # Copy main client files
    local client_files=("client.py" "exporters.py" "fans.py" "auth.py")
    for file in "${client_files[@]}"; do
        if [[ -f "$current_dir/$file" ]]; then
            cp "$current_dir/$file" "/opt/dcmon/"
            chmod 755 "/opt/dcmon/$file"
            print_success "Installed $file"
        else
            print_warning "File $file not found in $current_dir"
        fi
    done
    
    
    # Copy requirements.txt if exists
    if [[ -f "$current_dir/requirements.txt" ]]; then
        cp "$current_dir/requirements.txt" "/opt/dcmon/"
        print_success "Installed requirements.txt"
    fi
    
    # Create default config if it doesn't exist
    local config_file="/etc/dcmon/config.json"
    if [[ ! -f "$config_file" ]]; then
        cat > "$config_file" << 'EOF'
{
  "server_url": "http://your-server.com:8000",
  "collection_interval": 30,
  "exporters": {
    "ipmi": true,
    "apt": true,
    "nvme": true,
    "nvsmi": true
  }
}
EOF
        print_success "Created default config.json"
    fi
}

create_systemd_service() {
    print_step "Creating systemd service..."
    
    cat > /etc/systemd/system/dcmon-client.service << 'EOF'
[Unit]
Description=dcmon Client - Datacenter Monitoring Client
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/dcmon
ExecStart=/usr/bin/python3 /opt/dcmon/client.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=dcmon-client

[Install]
WantedBy=multi-user.target
EOF
    
    print_success "Created systemd service"
}

setup_server_and_register() {
    print_step "Setting up server configuration and registering client..."
    
    local config_file="/etc/dcmon/config.json"
    local server_url=""
    local admin_token=""
    
    echo
    echo "dcmon Server Configuration"
    echo "========================="
    
    # Get server URL
    read -p "Enter dcmon server URL [http://localhost:8000]: " -r server_url
    if [[ -z "$server_url" ]]; then
        server_url="http://localhost:8000"
    fi
    
    # Get admin token
    echo
    read -p "Enter admin token (from server installation): " -r admin_token
    if [[ -z "$admin_token" ]]; then
        print_error "Admin token is required for client registration"
        return 1
    fi
    
    # Update config.json with server URL
    if command -v python3 >/dev/null 2>&1; then
        if python3 -c "
import json
with open('$config_file', 'r') as f: config = json.load(f)
config['server_url'] = '$server_url'
with open('$config_file', 'w') as f: json.dump(config, f, indent=2)
" 2>/dev/null; then
            print_success "Updated server URL to: $server_url"
        else
            print_warning "Failed to update config.json automatically"
            echo "Please manually update server_url in $config_file"
            return 1
        fi
    else
        print_warning "Python3 not available for config update"
        echo "Please manually update server_url in $config_file"
        return 1
    fi
    
    # Register client with server (admin key only in memory)
    print_step "Registering client with server..."
    echo
    
    if python3 /opt/dcmon/client.py register "$admin_token" "$server_url"; then
        print_success "Client registered successfully with server!"
        return 0
    else
        print_error "Client registration failed"
        echo "Please check:"
        echo "  1. Server is running at $server_url"
        echo "  2. Admin key is correct"
        echo "  3. Network connectivity"
        return 1
    fi
}


enable_and_start_service() {
    print_step "Enabling and starting service..."
    
    if systemctl daemon-reload; then
        print_success "Reloaded systemd daemon"
    else
        print_warning "Failed to reload systemd daemon"
    fi
    
    if systemctl enable dcmon-client; then
        print_success "Enabled dcmon-client service"
    else
        print_error "Failed to enable service"
        return 1
    fi
    
    print_step "Starting dcmon-client service..."
    if systemctl start dcmon-client; then
        print_success "Started dcmon-client service"
        
        # Give it a moment to start and register
        sleep 2
        
        echo
        print_step "Service Status:"
        systemctl status dcmon-client --no-pager -l
        
        echo
        print_step "Recent logs:"
        journalctl -u dcmon-client --no-pager -n 10
    else
        print_error "Failed to start service"
        echo
        print_step "Error logs:"
        journalctl -u dcmon-client --no-pager -n 20
        return 1
    fi
    
    return 0
}

main() {
    echo "dcmon Client Installer V2"
    echo "========================="
    echo "🔐 Automatic registration with cryptographic keys"
    echo
    
    check_root
    
    print_step "Installing dcmon client..."
    echo
    
    # Installation steps
    create_directories || exit 1
    install_dependencies || exit 1
    install_files || exit 1
    create_systemd_service || exit 1
    
    # Setup configuration and register (prompts for server URL and admin key)
    setup_server_and_register || exit 1
    
    # Enable and start service (auto-registration happens on first start)
    enable_and_start_service || exit 1
    
    echo
    echo "========================================"
    print_success "Installation complete!"
    echo
    echo "🎉 Client will automatically register with the server"
    echo "🔑 Cryptographic keys generated automatically"
    echo "📊 Metrics collection started"
    echo
    echo "Useful commands:"
    echo "  sudo systemctl status dcmon-client     # Check status"
    echo "  sudo systemctl restart dcmon-client    # Restart service"
    echo "  sudo journalctl -u dcmon-client -f     # Follow logs"
    echo
    echo "Configuration files:"
    echo "  /etc/dcmon/config.json                 # Client configuration"
    echo "  /etc/dcmon/client.key                  # Private key (auto-generated)"
    echo "  /etc/dcmon/client.pub                  # Public key (auto-generated)"
    echo "  /etc/dcmon/client_token               # Client token (auto-generated)"
    echo
    echo "If registration fails, check:"
    echo "  1. Server is running and accessible"
    echo "  2. Server URL is correct in config.json"
    echo "  3. Check logs: sudo journalctl -u dcmon-client"
}

main "$@"