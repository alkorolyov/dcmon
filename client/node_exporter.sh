#!/bin/bash
###### node_exporter service ########

BIN_DIR='/usr/local/bin'
VAR_DIR ='/var/lib/node_exporter'

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

echo "=> Start service"
systemctl daemon-reload
systemctl start node_exporter

# check service status
status=$(systemctl is-active node_exporter)
if [[ "$status" == "active" ]]; then
    status="${GREEN}$status${NC}"
else
    status="${RED}$status${NC}"
fi
echo -e "=> Service status: $status"

systemctl enable node_exporter

echo "=> Delete tmp files"
rm -rf /tmp/node_exporter*/
rm -rf /tmp/node_exporter*

echo "=> Installation complete!"
