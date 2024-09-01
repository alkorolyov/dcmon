#!/bin/bash
###### node_exporter service ########

BIN_DIR='/usr/local/bin'
VAR_DIR='/var/lib/node_exporter'
SLEEP_TIME=15

# Define ANSI escape codes for colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

USER='node_exporter'
GROUP=$USER

echo -e "=> ${GREEN}Start installation of NODE_EXPORTER service${NC}"

if [[ $UID -ne 0 ]]; then
    echo "Installation should be run as root."
    exit
fi

echo "=> Download and extract latest node_exporter"
cd /tmp
latest_node_extractor=$(curl -s https://api.github.com/repos/prometheus/node_exporter/releases/latest | grep "browser_download_url.*linux-amd64" | cut -d '"' -f 4)
wget -q --show-progress $latest_node_extractor
tar vxf node_exporter*.tar.gz
cd node_exporter*/

echo "=> Create user/group"
sudo useradd -rs /bin/false $USER
sudo cp -f node_exporter $BIN_DIR
sudo chown $USER:$GROUP $BIN_DIR/node_exporter

sudo mkdir -p $VAR_DIR/proms
sudo chown -R $USER:$GROUP $VAR_DIR

echo "=> Copy exporters scripts"
sudo cp -r $EXPORTERS_DIR/* $VAR_DIR/proms/
sudo chown -R $USER:$GROUP $VAR_DIR/proms/

echo "=> Create service file"
SERVICE_CONTENT="
[Unit]
Description=Node Exporter
After=network-online.target

[Service]
User=$USER
Group=$GROUP
Type=simple
ExecStart=node_exporter --collector.textfile.directory $VAR_DIR/proms --collector.disable-defaults --collector.cpu --collector.diskstats --collector.filesystem --collector.netdev --collector.meminfo --collector.mdadm --collector.textfile

[Install]
WantedBy=multi-user.target
"
echo -e "$SERVICE_CONTENT" > /etc/systemd/system/node_exporter.service

echo "=> Create exporters runner service"
RUNNER_SERVICE_CONTENT="
[Unit]
Description=Run custom exporters loop
After=network-online.target

[Service]
User=$USER
Group=$GROUP
Type=simple
ExecStart=/bin/bash -c 'while true; do 
    for script in $VAR_DIR/proms/*.sh; do 
        {
            output_file=\"$VAR_DIR/proms/\$(basename \${script%.*}).prom\"; 
            sudo bash \$script > \$output_file.tmp 2>/dev/null && mv \$output_file.tmp \$output_file;
            rm \$output_file.tmp'
        } &
    done
    wait
    sleep $SLEEP_TIME; 
done'

Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
"
echo -e "$RUNNER_SERVICE_CONTENT" > /etc/systemd/system/exporters_runner.service

echo "=> Start services"
systemctl daemon-reload
systemctl start node_exporter
systemctl start exporters_runner

# check service status
node_exporter_status=$(systemctl is-active node_exporter)
exporters_runner_status=$(systemctl is-active exporters_runner)

if [[ "$node_exporter_status" == "active" ]]; then
    node_exporter_status="${GREEN}$node_exporter_status${NC}"
else
    node_exporter_status="${RED}$node_exporter_status${NC}"
fi

if [[ "$exporters_runner_status" == "active" ]]; then
    exporters_runner_status="${GREEN}$exporters_runner_status${NC}"
else
    exporters_runner_status="${RED}$exporters_runner_status${NC}"
fi

echo -e "=> Node Exporter service status: $node_exporter_status"
echo -e "=> Exporters Runner service status: $exporters_runner_status"

systemctl enable node_exporter
systemctl enable exporters_runner

echo "=> Delete tmp files"
rm -rf /tmp/node_exporter*/
rm -rf /tmp/node_exporter*

echo "=> Installation complete!"
