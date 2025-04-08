#!/bin/bash

# Function to check if input is a valid integer between 0 and 100
is_valid_speed() {
    [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -ge 0 ] && [ "$1" -le 100 ]
}

# If argument is provided, try to set the fan speed
if [ $# -eq 1 ] && is_valid_speed "$1"; then
    speed_hex=$(printf "0x%02x" "$1")
    echo "Setting fan speed to $1% (hex: $speed_hex) for both zones..."

    # Set fan speed for Zone 0 and Zone 1
    sudo ipmitool raw 0x30 0x70 0x66 0x01 0 "$speed_hex"
    sudo ipmitool raw 0x30 0x70 0x66 0x01 1 "$speed_hex"
    echo "Fan speed set successfully."
else
    if [ $# -eq 1 ]; then
        echo "Invalid speed value: $1. Please provide a number between 0 and 100."
        exit 1
    fi

    # Display current fan speeds
    hex_zone0=$(sudo ipmitool raw 0x30 0x70 0x66 0x00 0)
    hex_zone1=$(sudo ipmitool raw 0x30 0x70 0x66 0x00 1)

    clean_hex_zone0=$(echo "$hex_zone0" | tr -dc '[:alnum:]')
    clean_hex_zone1=$(echo "$hex_zone1" | tr -dc '[:alnum:]')

    decimal_zone0=$(printf "%d" "0x$clean_hex_zone0")
    decimal_zone1=$(printf "%d" "0x$clean_hex_zone1")

    echo "Zone 0 fan speed: $decimal_zone0%"
    echo "Zone 1 fan speed: $decimal_zone1%"
fi
