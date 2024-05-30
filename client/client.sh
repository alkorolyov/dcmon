apt remove docker-compose
curl -L "https://github.com/docker/compose/releases/download/v2.24.4/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
ln -s /usr/local/bin/docker-compose /usr/bin/docker-compose
apt-get update && sudo apt-get install -y gettext-base
wget -O docker-compose.yml https://raw.githubusercontent.com/jjziets/DCMontoring/main/client/docker-compose.yml-vast
wget -O /usr/local/bin/check-upgradable-packages.sh  https://github.com/jjziets/gddr6_temps/raw/master/update-package-count.sh;
chmod +x /usr/local/bin/check-upgradable-packages.sh;
sudo bash -c '(crontab -l 2>/dev/null; echo "0 * * * * /usr/local/bin/check-upgradable-packages.sh") | crontab -'
docker-compose pull
sed "s/__HOST_HOSTNAME__/$(hostname)/g" docker-compose.yml | docker-compose -f - up -d
