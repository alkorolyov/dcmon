#!/bin/bash

VAR_DIR='/var/lib/node_exporter'
SLEEP_TIME=15

while true; do 
    for script in $VAR_DIR/exporters/*.sh; do 
        {
            prom_file=\"$VAR_DIR/exporters/\$(basename \${script%.*}).prom\"; 
            sudo bash \$script > \$prom_file.tmp 2>/dev/null && mv \$prom_file.tmp \$prom_file;
            rm \$prom_file.tmp
        } &
    done
    wait
    sleep $SLEEP_TIME; 
done
