#!/bin/bash

# Run ipmitool command to get hex values for both zones
hex_zone0=$(sudo ipmitool raw 0x30 0x70 0x66 0x00 0)
hex_zone1=$(sudo ipmitool raw 0x30 0x70 0x66 0x00 1)

# Clean up the hex values by removing non-numeric characters
clean_hex_zone0=$(echo "$hex_zone0" | tr -dc '[:alnum:]')
clean_hex_zone1=$(echo "$hex_zone1" | tr -dc '[:alnum:]')

# Convert cleaned hex values to decimals
decimal_zone0=$(printf "%d" "0x$clean_hex_zone0")
decimal_zone1=$(printf "%d" "0x$clean_hex_zone1")

# Output the decimal values
echo "Zone 0 fan speed: $decimal_zone0%"
echo "Zone 1 fan speed: $decimal_zone1%"
