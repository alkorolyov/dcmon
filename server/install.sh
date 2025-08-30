#!/bin/bash
#
# dcmon Server Installer
# Creates systemd service and installs dcmon server
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
        "/etc/dcmon-server"
        "/opt/dcmon-server" 
        "/var/lib/dcmon"
        "/var/log/dcmon-server"
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
    if apt install -y python3 python3-pip python3-venv >/dev/null 2>&1; then
        print_success "Installed Python3 and pip"
    else
        print_error "Failed to install Python dependencies"
        return 1
    fi
    
    return 0
}

create_virtual_environment() {
    print_step "Creating Python virtual environment..."
    
    local venv_path="/opt/dcmon-server/venv"
    
    # Create virtual environment
    if python3 -m venv "$venv_path"; then
        print_success "Created virtual environment"
    else
        print_error "Failed to create virtual environment"
        return 1
    fi
    
    # Install Python dependencies
    local pip_path="$venv_path/bin/pip"
    local requirements_file="$(dirname "$0")/requirements.txt"
    
    if [[ -f "$requirements_file" ]]; then
        if "$pip_path" install -r "$requirements_file" >/dev/null 2>&1; then
            print_success "Installed Python dependencies from requirements.txt"
        else
            print_warning "Failed to install from requirements.txt, installing manually"
            if "$pip_path" install fastapi uvicorn[standard] aiosqlite pydantic python-multipart >/dev/null 2>&1; then
                print_success "Installed Python dependencies manually"
            else
                print_error "Failed to install Python dependencies"
                return 1
            fi
        fi
    else
        if "$pip_path" install fastapi uvicorn[standard] aiosqlite pydantic python-multipart >/dev/null 2>&1; then
            print_success "Installed Python dependencies"
        else
            print_error "Failed to install Python dependencies"
            return 1
        fi
    fi
    
    return 0
}

install_files() {
    print_step "Installing server files..."
    
    local current_dir="$(dirname "$0")"
    local server_files=("main.py" "database.py")
    
    for file in "${server_files[@]}"; do
        if [[ -f "$current_dir/$file" ]]; then
            cp "$current_dir/$file" "/opt/dcmon-server/"
            print_success "Installed $file"
        else
            print_warning "File $file not found in $current_dir"
        fi
    done
    
    # Create default config
    local config_file="/etc/dcmon-server/config.json"
    if [[ ! -f "$config_file" ]]; then
        cat > "$config_file" << 'EOF'
{
  "database_path": "/var/lib/dcmon/dcmon.db",
  "host": "0.0.0.0",
  "port": 8000,
  "log_level": "info",
  "cleanup_days": 7
}
EOF
        print_success "Created default config.json"
    fi
}

create_user() {
    print_step "Creating dcmon-server user..."
    
    # Check if user already exists
    if id "dcmon-server" >/dev/null 2>&1; then
        print_success "User dcmon-server already exists"
    else
        # Create system user
        if useradd --system --home-dir "/opt/dcmon-server" \
                  --shell "/usr/sbin/nologin" --comment "dcmon Server" \
                  "dcmon-server"; then
            print_success "Created dcmon-server user"
        else
            print_error "Failed to create dcmon-server user"
            return 1
        fi
    fi
    
    # Set ownership of directories
    local dirs=(
        "/opt/dcmon-server"
        "/var/lib/dcmon"
        "/var/log/dcmon-server"
    )
    
    for dir in "${dirs[@]}"; do
        if chown -R dcmon-server:dcmon-server "$dir"; then
            print_success "Set ownership of $dir"
        else
            print_warning "Failed to set ownership of $dir"
        fi
    done
    
    return 0
}

create_systemd_service() {
    print_step "Creating systemd service..."
    
    cat > /etc/systemd/system/dcmon-server.service << 'EOF'
[Unit]
Description=dcmon Server - Datacenter Monitoring Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=dcmon-server
Group=dcmon-server
WorkingDirectory=/opt/dcmon-server
Environment=PATH=/opt/dcmon-server/venv/bin
ExecStart=/opt/dcmon-server/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=dcmon-server

[Install]
WantedBy=multi-user.target
EOF
    
    print_success "Created systemd service"
}


enable_service() {
    print_step "Enabling service..."
    
    if systemctl daemon-reload; then
        print_success "Reloaded systemd daemon"
    else
        print_warning "Failed to reload systemd daemon"
    fi
    
    if systemctl enable dcmon-server; then
        print_success "Enabled dcmon-server service"
    else
        print_error "Failed to enable service"
        return 1
    fi
    
    echo
    read -p "Start dcmon-server service now? [y/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if systemctl start dcmon-server; then
            print_success "Started dcmon-server service"
            
            echo
            print_step "Service Status:"
            systemctl status dcmon-server --no-pager -l
            
            echo
            print_step "Server should be available at:"
            echo "  http://localhost:8000"
            echo "  http://localhost:8000/docs (API documentation)"
        else
            print_error "Failed to start service"
            return 1
        fi
    fi
    
    return 0
}

main() {
    echo "dcmon Server Installer"
    echo "========================"
    
    check_root
    
    print_step "Installing dcmon server..."
    echo
    
    # Installation steps
    create_directories || exit 1
    install_dependencies || exit 1
    create_user || exit 1
    install_files || exit 1
    create_virtual_environment || exit 1
    create_systemd_service || exit 1
    enable_service || exit 1
    
    echo
    echo "========================================"
    print_success "Installation complete!"
    echo
    echo "Useful commands:"
    echo "  sudo systemctl status dcmon-server    # Check status"
    echo "  sudo systemctl restart dcmon-server   # Restart service"
    echo "  sudo journalctl -u dcmon-server -f    # Follow logs"
    echo
    echo "Server endpoints:"
    echo "  http://localhost:8000                 # Server info"
    echo "  http://localhost:8000/health          # Health check"
    echo "  http://localhost:8000/docs            # API documentation"
    echo "  http://localhost:8000/api/clients     # List clients"
}

main "$@"