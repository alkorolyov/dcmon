#!/bin/bash

# Get user input for SSH connection details
read -p "Enter SSH username: " user
read -p "Enter SSH hostname or IP address: " host
read -p "Enter SSH port: " port

# Get folder names
folder_name=$(hostname)
vast_dir="/var/lib/vastai_kaalia"

#install pv and pixz 
echo -e "\nInstall pv pzstd"
apt -qq install pv zstd -y

# Stop services
echo -e "\nStopping services..."
systemctl stop cron
systemctl stop vastai
systemctl stop docker.socket
systemctl stop docker

# Check and create folder if it does not exist
echo -e "\nEnsuring the backup folder exists on remote server..."
# mkdir -p /mnt/backup/vast/$folder_name
ssh user@host -p port "mkdir -p /mnt/backup/vast/$folder_name"

# Tar the folder /var/lib/docker and send it to the server
echo -e "\nSending the tar file to server..."

cat $vast_dir/machine_id |  ssh $user@$host -p $port "cat > /mnt/backup/vast/$folder_name/machine_id"
cat $vast_dir/host_port_range |  ssh $user@$host -p $port "cat > /mnt/backup/vast/$folder_name/host_port_range"
tar -cf - /var/lib/docker | pv | pzstd - | ssh $user@$host -p $port "cat > /mnt/backup/vast/$folder_name/docker.tar.zst"
 
# cp $vast_dir/host_port_range /mnt/backup/vast/$folder_name
# cp $vast_dir/machine_id /mnt/backup/vast/$folder_name
# tar -cf - /var/lib/docker | pv | pzstd - > /mnt/backup/vast/$folder_name/docker.tar.zst

# Start services
echo -e "\n Restarting services ..."
systemctl start docker
systemctl start docker.socket
systemctl start vastai
systemctl start cron

echo -e "\n Done"
