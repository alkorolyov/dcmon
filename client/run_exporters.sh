#!/bin/bash

VAR_DIR='/var/lib/node_exporter'
SLEEP_TIME=15

while true; do
    for script in $VAR_DIR/exporters/*.sh; do
        {
            #echo -e "executing $script";
            prom_file="$VAR_DIR/exporters/$(basename ${script%.>
            sudo bash $script > $prom_file.tmp 2>/dev/null && m>        
        } &
    done
    wait
    # echo "done";
    sleep $SLEEP_TIME;
done
