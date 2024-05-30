# dcmon
DataCenter monitoring for VastAI

# Install client part

edit /etc/docker/daemon.json:

`"registry-mirrors":  ["https://mirror.gcr.io", "https://daocloud.io", "https://c.163.com/", "https://registry.docker-cn.com"]`

run install.sh as root

# Install server part

Replace this with your Vast API key `- "--api-key=vastkey"`

run install.sh as root
