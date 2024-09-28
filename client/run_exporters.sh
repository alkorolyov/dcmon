#!/bin/bash

# Check if the script is run as root
if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root. Exiting..."
    exit 1
fi

VAR_DIR=${1:-"."}
SLEEP_TIME=${2:-"15"}  # Sleep time in seconds

mkdir -p "$VAR_DIR/proms"

# Infinite loop to repeatedly execute scripts.
while true; do
    for script in "$VAR_DIR/exporters/"*.sh; do
        {
            name=$(basename "${script%.*}")
            prom_file="$VAR_DIR/proms/$name.prom"
            
            if timeout $((SLEEP_TIME - 1)) bash "$script" > "$prom_file.tmp" 2>> "$VAR_DIR/errors.log"; then
                mv "$prom_file.tmp" "$prom_file"
            elif [ $? -eq 124 ]; then
                echo "$(date +'%Y-%m-%d %H:%M:%S') - Execution of $name timed out" >> "$VAR_DIR/errors.log"
            else
                echo "$(date +'%Y-%m-%d %H:%M:%S') - Execution of $name failed" >> "$VAR_DIR/errors.log"
            fi
        } &
    done

    wait

    sleep "$SLEEP_TIME"
done
