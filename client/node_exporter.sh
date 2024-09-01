#!/bin/bash
###### node_exporter service ########

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
latest_node_extractor=$(curl -s https://api.github.com/repos/prometheus/node_exporter/releases/latest | grep "browser_download_url.*linux-amd64" | cut -d '"' -f 4)
wget -q --show-progress $latest_node_extractor
tar vxf node_exporter*.tar.gz

echo "=> Create user/group"
sudo useradd -rs /bin/false $USER
sudo mkdir -p $VAR_DIR
sudo cp -R exporters $VAR_DIR/exporters
#sudo cp run_exporters.sh $VAR_DIR
sudo cp node_exporter*/node_exporter $VAR_DIR
sudo chown -R $USER:$GROUP $VAR_DIR

rm -rf node_exporter*

echo "=> Create service file"
NODE_EXPORTER_SERVICE="
[Unit]
Description=Node Exporter
After=network-online.target

[Service]
User=$USER
Group=$GROUP
Type=simple
ExecStart=$VAR_DIR/node_exporter --collector.textfile.directory $VAR_DIR/exporters --collector.disable-defaults --collector.cpu --collector.diskstats --collector.filesystem --collector.netdev --collector.meminfo --collector.mdadm --collector.textfile

[Install]
WantedBy=multi-user.target
"
echo -e "$NODE_EXPORTER_SERVICE" > /etc/systemd/system/node_exporter.service

echo "=> Create exporters runner service"
RUN_EXPORTERS_SERVICE="
[Unit]
Description=Run custom exporters loop
After=network-online.target

[Service]
User=$USER
Group=$GROUP
Type=simple
ExecStart=/bin/bash -c 'while true; do 
    for script in $VAR_DIR/exporters/*.sh; do 
        {
            prom_file=\"$VAR_DIR/exporters/\$(basename \${script%.*}).prom\"; 
            sudo bash \$script > \$prom_file.tmp 2>/dev/null && mv \$prom_file.tmp \$prom_file;
            rm \$prom_file.tmp'
        } &
    done
    wait
    sleep $SLEEP_TIME; 
done'

[Install]
WantedBy=multi-user.target
"
echo -e "$RUN_EXPORTERS_SERVICE" > /etc/systemd/system/run_exporters.service

echo "=> Start services"
systemctl daemon-reload
systemctl start node_exporter
systemctl start run_exporters

systemctl enable node_exporter
systemctl enable run_exporters

echo "=> Installation complete!"
