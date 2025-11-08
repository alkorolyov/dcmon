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

install_ipmicfg() {
    print_step "Installing ipmicfg for Supermicro PSU monitoring..."
    
    # Install gdown for downloading ipmicfg
    if python3 -m pip install gdown==4.6.0 >/dev/null 2>&1; then
        print_success "Installed gdown"
    else
        print_warning "Failed to install gdown - ipmicfg installation skipped"
        return 0
    fi
    
    # Create temporary directory for download
    local temp_dir=$(mktemp -d)
    cd "$temp_dir"
    
    # Download ipmicfg using gdown
    if python3 -m gdown --id 16XOUHmXUr2ckwAunKK01wMsHzB6xEIsx --output ipmicfg >/dev/null 2>&1; then
        print_success "Downloaded ipmicfg"
    else
        print_warning "Failed to download ipmicfg - PSU monitoring will be disabled"
        rm -rf "$temp_dir"
        return 0
    fi
    
    # Install ipmicfg to system path
    if mv ipmicfg /usr/local/bin/ipmicfg && chmod 755 /usr/local/bin/ipmicfg; then
        print_success "Installed ipmicfg to /usr/local/bin/ipmicfg"
    else
        print_warning "Failed to install ipmicfg - PSU monitoring will be disabled"
        rm -rf "$temp_dir"
        return 0
    fi
    
    # Clean up
    rm -rf "$temp_dir"
    
    # Verify installation
    if /usr/local/bin/ipmicfg -ver >/dev/null 2>&1; then
        print_success "ipmicfg installation verified - PSU monitoring enabled"
    else
        print_warning "ipmicfg verification failed - PSU monitoring may not work"
    fi
    
    return 0
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
        print_error "Failed to install Python dependencies: requirements.txt is missing"
        return 1
    fi
    
    # Install ipmicfg for Supermicro PSU monitoring
    install_ipmicfg
    
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
    local config_file="/etc/dcmon/config.yaml"
    if [[ ! -f "$config_file" ]]; then
        cat > "$config_file" << 'EOF'
server_url: "http://your-server.com:8000"
collection_interval: 30
exporters:
  ipmi: true
  apt: true
  nvme: true
  nvsmi: true
log_level: "INFO"
EOF
        print_success "Created default config.yaml"
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
ExecStart=/usr/bin/python3 /opt/dcmon/client.py -c /etc/dcmon/config.yaml
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
    
    local config_file="/etc/dcmon/config.yaml"
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
    
    # Update config.yaml with server URL
    if command -v python3 >/dev/null 2>&1; then
        if python3 -c "
import yaml
with open('$config_file', 'r') as f: config = yaml.safe_load(f)
config['server_url'] = '$server_url'
with open('$config_file', 'w') as f: yaml.dump(config, f, default_flow_style=False)
" 2>/dev/null; then
            print_success "Updated server URL to: $server_url"
        else
            print_warning "Failed to update config.yaml automatically"
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
    
    if python3 /opt/dcmon/main.py register "$admin_token" "$server_url"; then
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

get_server_url_from_config() {
    local config_file="/etc/dcmon/config.yaml"
    if [[ -f "$config_file" ]]; then
        python3 -c "
import yaml
try:
    with open('$config_file', 'r') as f:
        config = yaml.safe_load(f)
    print(config.get('server_url', 'http://localhost:8000'))
except:
    print('http://localhost:8000')
" 2>/dev/null || echo "http://localhost:8000"
    else
        echo "http://localhost:8000"
    fi
}

validate_registration() {
    local token_file="/etc/dcmon/client_token"
    
    # Check if token file exists
    if [[ ! -f "$token_file" ]]; then
        return 1  # No token file
    fi
    
    # Get server URL and token
    local server_url=$(get_server_url_from_config)
    local token=$(cat "$token_file" 2>/dev/null || echo "")
    
    if [[ -z "$token" ]]; then
        return 1  # Empty token
    fi
    
    # Test token with server using client verification endpoint
    if curl -s -f --max-time 10 \
        -H "Authorization: Bearer $token" \
        "$server_url/api/client/verify" > /dev/null 2>&1; then
        return 0  # Valid registration
    else
        return 1  # Invalid token or server unreachable
    fi
}

check_installation_state() {
    if [[ ! -f "/etc/systemd/system/dcmon-client.service" ]]; then
        print_step "📦 Client not installed"
        return 2  # Full installation needed
    fi
    
    if validate_registration; then
        print_success "✅ Client already installed and registered"
        return 0  # Fully operational
    else
        print_warning "⚠️ Client installed but registration invalid/missing"
        return 1  # Registration needed
    fi
}

retry_registration() {
    local server_url=""
    local admin_token=""
    
    echo
    echo "🔄 Client Registration"
    echo "====================="
    
    # Get server URL (use existing config or prompt)
    server_url=$(get_server_url_from_config)
    if [[ "$server_url" == "http://localhost:8000" ]]; then
        echo
        read -p "Enter dcmon server URL [$server_url]: " -r input_url
        if [[ -n "$input_url" ]]; then
            server_url="$input_url"
            # Update config with new URL
            update_config_server_url "$server_url"
        fi
    fi
    
    # Get admin token
    echo
    read -s -p "Enter admin token: " admin_token
    echo
    if [[ -z "$admin_token" ]]; then
        print_error "Admin token is required for client registration"
        return 1
    fi
    
    print_step "Attempting client registration..."
    
    # Attempt registration using the new main.py
    if echo "$admin_token" | python3 /opt/dcmon/main.py --auth-dir /etc/dcmon --server "$server_url" --once; then
        print_success "✅ Registration successful!"
        
        # Set proper permissions
        chown dcmon-client:dcmon-client /etc/dcmon/client_token
        chmod 600 /etc/dcmon/client_token
        
        # Start/restart service
        systemctl daemon-reload
        systemctl enable dcmon-client
        systemctl restart dcmon-client
        
        print_success "🚀 Client service started successfully"
        return 0
    else
        print_error "❌ Registration failed"
        echo "Please check:"
        echo "  • Admin token is correct"
        echo "  • Server URL is accessible: $server_url"
        echo "  • Server is running and accepting registrations"
        return 1
    fi
}

update_config_server_url() {
    local server_url="$1"
    local config_file="/etc/dcmon/config.yaml"
    
    if command -v python3 >/dev/null 2>&1; then
        python3 -c "
import yaml
try:
    with open('$config_file', 'r') as f:
        config = yaml.safe_load(f) or {}
    config['server_url'] = '$server_url'
    with open('$config_file', 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
except Exception as e:
    print(f'Warning: Failed to update config: {e}')
" 2>/dev/null || true
    fi
}

main() {
    echo "dcmon Client Installer V2"
    echo "========================="
    echo "🔐 Automatic registration with cryptographic keys"
    echo
    
    check_root
    
    # Check current installation state
    check_installation_state
    case $? in
        0) 
            echo
            print_success "Nothing to do - client is fully operational"
            echo
            echo "Useful commands:"
            echo "  sudo systemctl status dcmon-client     # Check status"
            echo "  sudo systemctl restart dcmon-client    # Restart service"  
            echo "  sudo journalctl -u dcmon-client -f     # Follow logs"
            exit 0
            ;;
        1)
            echo
            print_step "Retrying registration only..."
            retry_registration || {
                print_error "Registration failed. Run installer again with correct admin token."
                exit 1
            }
            ;;
        2)
            echo
            print_step "Performing full installation..."
            
            # Installation steps
            create_directories || exit 1
            install_dependencies || exit 1
            install_files || exit 1
            create_systemd_service || exit 1
            
            # Attempt registration
            retry_registration || {
                print_error "Installation completed but registration failed."
                print_warning "Run installer again to retry registration."
                exit 1
            }
            ;;
    esac
    
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
    echo "  /etc/dcmon/config.yaml                 # Client configuration"
    echo "  /etc/dcmon/client.key                  # Private key (auto-generated)"
    echo "  /etc/dcmon/client.pub                  # Public key (auto-generated)"
    echo "  /etc/dcmon/client_token               # Client token (auto-generated)"
    echo
    echo "If registration fails, check:"
    echo "  1. Server is running and accessible"
    echo "  2. Server URL is correct in config.yaml"
    echo "  3. Check logs: sudo journalctl -u dcmon-client"
}

main "$@"