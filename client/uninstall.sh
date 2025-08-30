#!/bin/bash
#
# dcmon Client Uninstaller
# Removes dcmon client installation completely
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
    echo -e "${RED}⚠ WARNING: This will completely remove dcmon client!${NC}"
    echo "This includes:"
    echo "  - Service files and configuration"
    echo "  - API key and settings"  
    echo "  - Client application files"
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
    if systemctl is-active --quiet dcmon-client; then
        if systemctl stop dcmon-client; then
            print_success "Stopped dcmon-client service"
        else
            print_warning "Failed to stop service"
        fi
    fi
    
    # Disable service if enabled
    if systemctl is-enabled --quiet dcmon-client; then
        if systemctl disable dcmon-client; then
            print_success "Disabled dcmon-client service"
        else
            print_warning "Failed to disable service"
        fi
    fi
}

remove_systemd_service() {
    print_step "Removing systemd service..."
    
    local service_file="/etc/systemd/system/dcmon-client.service"
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
        "/opt/dcmon"
        "/etc/dcmon" 
        "/var/log/dcmon"
    )
    
    for directory in "${directories[@]}"; do
        if [[ -d "$directory" ]]; then
            rm -rf "$directory"
            print_success "Removed directory: $directory"
        fi
    done
}

remove_python_dependencies() {
    print_step "Removing Python dependencies..."
    
    # Only remove aiohttp if it was installed system-wide
    if python3 -m pip show aiohttp >/dev/null 2>&1; then
        read -p "Remove aiohttp Python package? [y/N]: " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if python3 -m pip uninstall -y aiohttp >/dev/null 2>&1; then
                print_success "Removed aiohttp Python package"
            else
                print_warning "Failed to remove aiohttp package"
            fi
        fi
    fi
}

remove_system_tools() {
    print_step "Checking system tools..."
    
    # Check if tools were installed and offer to remove them
    local tools_to_check=("ipmitool" "nvme-cli")
    local tools_to_remove=()
    
    for tool in "${tools_to_check[@]}"; do
        if command -v "$tool" >/dev/null 2>&1; then
            tools_to_remove+=("$tool")
        fi
    done
    
    if [[ ${#tools_to_remove[@]} -gt 0 ]]; then
        echo "Found system tools: ${tools_to_remove[*]}"
        read -p "Remove these tools? (They may be used by other applications) [y/N]: " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if apt remove -y "${tools_to_remove[@]}" >/dev/null 2>&1; then
                print_success "Removed system tools: ${tools_to_remove[*]}"
            else
                print_warning "Failed to remove some system tools"
            fi
        else
            print_success "Kept system tools (they may be used elsewhere)"
        fi
    fi
}

cleanup_logs() {
    print_step "Cleaning up logs..."
    
    if command -v journalctl >/dev/null 2>&1; then
        if journalctl --vacuum-time=1s --unit=dcmon-client >/dev/null 2>&1; then
            print_success "Cleaned up systemd logs"
        fi
    fi
}

check_remaining_files() {
    print_step "Checking for remaining files..."
    
    local remaining_paths=()
    local check_paths=(
        "/opt/dcmon"
        "/etc/dcmon"
        "/var/log/dcmon"
        "/etc/systemd/system/dcmon-client.service"
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
        print_success "All dcmon client files removed successfully"
    fi
}

main() {
    echo "dcmon Client Uninstaller"
    echo "========================"
    
    check_root
    confirm_uninstall
    
    echo
    print_step "Uninstalling dcmon client..."
    echo
    
    # Uninstallation steps - continue even if some fail
    stop_and_disable_service || true
    remove_systemd_service || true
    remove_directories || true
    remove_python_dependencies || true
    remove_system_tools || true
    cleanup_logs || true
    check_remaining_files || true
    
    echo
    echo "========================================"
    print_success "dcmon client uninstallation complete!"
    echo
    echo "To reinstall dcmon client, run the install script again."
}

main "$@"