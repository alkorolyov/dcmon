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
    if python3 -m pip install aiohttp >/dev/null 2>&1; then
        print_success "Installed Python dependencies"
    else
        print_error "Failed to install Python dependencies"
        return 1
    fi
    
    return 0
}

install_files() {
    print_step "Installing client files..."
    
    local current_dir="$(dirname "$0")"
    
    # Copy main client files
    local client_files=("client.py" "exporters.py" "fans.py")
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

setup_api_key() {
    print_step "Setting up API key..."
    
    echo
    echo "=================================================="
    echo "IMPORTANT: API Key Setup Required"
    echo "=================================================="
    echo "You need an API key from your dcmon server."
    echo "Contact your administrator or register at:"
    echo "  http://your-server:8000/api/register"
    echo
    
    read -p "Enter your dcmon API key: " -r api_key
    
    if [[ -n "$api_key" ]]; then
        echo "$api_key" > /etc/dcmon/api_key
        chmod 600 /etc/dcmon/api_key
        print_success "API key saved"
        return 0
    else
        print_warning "API key not set. You must set it before starting the service:"
        echo "  echo 'YOUR_API_KEY' | sudo tee /etc/dcmon/api_key > /dev/null"
        echo "  sudo chmod 600 /etc/dcmon/api_key"
        return 1
    fi
}

setup_server_url() {
    print_step "Setting up server URL..."
    
    local config_file="/etc/dcmon/config.json"
    
    echo
    read -p "Enter your dcmon server URL [http://localhost:8000]: " -r server_url
    
    if [[ -z "$server_url" ]]; then
        server_url="http://localhost:8000"
    fi
    
    # Update config.json with proper server URL
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
    
    return 0
}

enable_service() {
    print_step "Enabling service..."
    
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
    
    echo
    read -p "Start dcmon-client service now? [y/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if systemctl start dcmon-client; then
            print_success "Started dcmon-client service"
            
            echo
            print_step "Service Status:"
            systemctl status dcmon-client --no-pager -l
        else
            print_error "Failed to start service"
            print_warning "Check the API key and server URL configuration"
            return 1
        fi
    fi
    
    return 0
}

main() {
    echo "dcmon Client Installer"
    echo "======================"
    
    check_root
    
    print_step "Installing dcmon client..."
    echo
    
    # Installation steps
    create_directories || exit 1
    install_dependencies || exit 1
    install_files || exit 1
    create_systemd_service || exit 1
    
    # Setup configuration
    setup_server_url || exit 1
    has_api_key=$(setup_api_key && echo 1 || echo 0)
    
    if [[ $has_api_key -eq 1 ]]; then
        enable_service || exit 1
    else
        print_warning "Service is installed but not started."
        echo "Set your API key and then run:"
        echo "  sudo systemctl start dcmon-client"
    fi
    
    echo
    echo "========================================"
    print_success "Installation complete!"
    echo
    echo "Useful commands:"
    echo "  sudo systemctl status dcmon-client    # Check status"
    echo "  sudo systemctl restart dcmon-client   # Restart service"
    echo "  sudo journalctl -u dcmon-client -f    # Follow logs"
    echo
    echo "Configuration files:"
    echo "  /etc/dcmon/config.json               # Client configuration"
    echo "  /etc/dcmon/api_key                   # API key"
    echo
    echo "Log files:"
    echo "  sudo journalctl -u dcmon-client      # Service logs"
}

main "$@"