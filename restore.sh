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


# Tar the folder /var/lib/docker and send it to the server
echo -e "\nSending the tar file to server..."
cp /mnt/backup/vast/$folder_name $vast_dir
cp /mnt/backup/vast/$folder_name $vast_dir

pzstd -dc /mnt/backup/vast/$folder_name/docker.tar.zst | pv --line-mode | sudo tar -xf - -C /

