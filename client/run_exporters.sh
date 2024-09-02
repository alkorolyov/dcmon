#!/bin/bash

VAR_DIR='/var/lib/node_exporter'
SLEEP_TIME=15  # sleep time in seconds

while true; do
    for script in $VAR_DIR/exporters/*.sh; do
        {
            #echo -e "executing $script";
            prom_file="$VAR_DIR/exporters/$(basename ${script%.*}).prom"
            bash $script > $prom_file.tmp 2>/dev/null && mv $prom_file.tmp $prom_file;
        } &
    done
    wait
    # echo "done";
    sleep $SLEEP_TIME;
done
