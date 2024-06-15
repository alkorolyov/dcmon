#!/bin/bash

# Get folder names
folder_name=$(hostname)
vast_dir="/var/lib/vastai_kaalia"


#install pv and pixz 
echo -e "\nInstall pv pzstd"
apt -qq install pv zstd -y

# Stop services
echo -e "\nStopping services..."
systemctl stop cron
systemctl stop docker.socket
systemctl stop docker
systemctl stop vastai

# Check and create folder if it does not exist
echo -e "\nEnsuring the backup folder exists on remote server..."
mkdir -p /mnt/backup/vast/$folder_name

# Tar the folder /var/lib/docker and send it to the server
echo -e "\nSending the tar file to server..."
cp $vast_dir/host_port_range /mnt/backup/vast/$folder_name
cp $vast_dir/machine_id /mnt/backup/vast/$folder_name
tar -cf - /var/lib/docker | pv | pzstd - > /mnt/backup/vast/$folder_name/docker.tar.zst

echo -e "\nDone!"
