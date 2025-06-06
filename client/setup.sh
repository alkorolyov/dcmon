#!/bin/bash
###### node_exporter service ########

VAR_DIR='/var/lib/node_exporter'
TIMEOUT=30  # in seconds

echo -e "=> Start installation of NODE_EXPORTER service"

if [[ $UID -ne 0 ]]; then
    echo "Installation should be run as root."
    exit
fi

echo "=> Install apt dependencies"
apt-get install -qq nvme-cli jq ipmitool git

cd /tmp

echo "=> Clone repo"
git clone https://github.com/alkorolyov/dcmon
cd dcmon/client

echo "=> Download and extract latest node_exporter"
latest_node_extractor=$(curl -s https://api.github.com/repos/prometheus/node_exporter/releases/latest | grep "browser_download_url.*linux-amd64" | cut -d '"' -f 4)
wget -q --show-progress $latest_node_extractor
tar vxf node_exporter*.tar.gz

echo "=> Copy program files"
mkdir -p $VAR_DIR
cp -R exporters $VAR_DIR/exporters
cp run_exporters.sh $VAR_DIR
cp node_exporter*/node_exporter $VAR_DIR

echo "=> Create service file"
NODE_EXPORTER_SERVICE="
[Unit]
Description=Node Exporter
After=network-online.target

[Service]
Type=simple
ExecStart=$VAR_DIR/node_exporter --collector.textfile.directory $VAR_DIR/proms --collector.disable-defaults --collector.cpu --collector.diskstats --collector.filesystem --collector.netdev --collector.meminfo --collector.mdadm --collector.textfile
Restart=on-failure
RestartSec=$TIMEOUT

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
#User=$USER
#Group=$GROUP
Type=simple
ExecStart=/bin/bash $VAR_DIR/run_exporters.sh $VAR_DIR $TIMEOUT
Restart=on-failure
RestartSec=$TIMEOUT

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


echo "=> Remove installation files"
cd /
rm -rf /tmp/dcmon

echo "=> Installation complete!"
