#!/bin/bash
#
# dcmon Server Uninstaller
# Removes dcmon server installation completely
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
        print_error "This uninstaller must be run as root (sudo)"
        exit 1
    fi
}

confirm_uninstall() {
    echo -e "${RED}⚠ WARNING: This will completely remove dcmon server and all data!${NC}"
    echo "This includes:"
    echo "  - Service files and configuration"
    echo "  - All stored metrics data"  
    echo "  - Database files"
    echo "  - User account"
    echo
    
    read -p "Are you sure you want to continue? Type 'yes' to confirm: " -r
    if [[ ! $REPLY == "yes" ]]; then
        echo "Uninstallation cancelled."
        exit 0
    fi
}

stop_and_disable_service() {
    print_step "Stopping and disabling service..."
    
    # Stop service if running
    if systemctl is-active --quiet dcmon-server; then
        if systemctl stop dcmon-server; then
            print_success "Stopped dcmon-server service"
        else
            print_warning "Failed to stop service"
        fi
    fi
    
    # Disable service if enabled
    if systemctl is-enabled --quiet dcmon-server; then
        if systemctl disable dcmon-server; then
            print_success "Disabled dcmon-server service"
        else
            print_warning "Failed to disable service"
        fi
    fi
}

remove_systemd_service() {
    print_step "Removing systemd service..."
    
    local service_file="/etc/systemd/system/dcmon-server.service"
    if [[ -f "$service_file" ]]; then
        rm -f "$service_file"
        print_success "Removed systemd service file"
        
        if systemctl daemon-reload; then
            print_success "Reloaded systemd daemon"
        else
            print_warning "Failed to reload systemd daemon"
        fi
    fi
}

remove_directories() {
    print_step "Removing directories and files..."
    
    local directories=(
        "/opt/dcmon-server"
        "/etc/dcmon-server" 
        "/var/lib/dcmon"
        "/var/log/dcmon-server"
    )
    
    for directory in "${directories[@]}"; do
        if [[ -d "$directory" ]]; then
            rm -rf "$directory"
            print_success "Removed directory: $directory"
        fi
    done
}

remove_user() {
    print_step "Removing user account..."
    
    if id "dcmon-server" >/dev/null 2>&1; then
        if userdel "dcmon-server"; then
            print_success "Removed dcmon-server user"
        else
            print_warning "Failed to remove dcmon-server user"
        fi
    fi
}


cleanup_logs() {
    print_step "Cleaning up logs..."
    
    if command -v journalctl >/dev/null 2>&1; then
        if journalctl --vacuum-time=1s --unit=dcmon-server >/dev/null 2>&1; then
            print_success "Cleaned up systemd logs"
        fi
    fi
}

check_remaining_files() {
    print_step "Checking for remaining files..."
    
    local remaining_paths=()
    local check_paths=(
        "/opt/dcmon-server"
        "/etc/dcmon-server"
        "/var/lib/dcmon" 
        "/var/log/dcmon-server"
        "/etc/systemd/system/dcmon-server.service"
    )
    
    for path in "${check_paths[@]}"; do
        if [[ -e "$path" ]]; then
            remaining_paths+=("$path")
        fi
    done
    
    if [[ ${#remaining_paths[@]} -gt 0 ]]; then
        echo
        print_warning "Some files may remain:"
        for path in "${remaining_paths[@]}"; do
            echo "  $path"
        done
        echo "You may need to remove these manually."
    else
        print_success "All dcmon server files removed successfully"
    fi
}

main() {
    echo "dcmon Server Uninstaller"
    echo "=========================="
    
    check_root
    confirm_uninstall
    
    echo
    print_step "Uninstalling dcmon server..."
    echo
    
    # Uninstallation steps - continue even if some fail
    stop_and_disable_service || true
    remove_systemd_service || true
    remove_directories || true
    remove_user || true
    cleanup_logs || true
    check_remaining_files || true
    
    echo
    echo "========================================"
    print_success "dcmon server uninstallation complete!"
    echo
    echo "To reinstall dcmon server, run the install script again."
}

main "$@"