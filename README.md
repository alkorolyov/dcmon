### dcmon
DataCenter monitoring for VastAI

### Install client part

edit /etc/docker/daemon.json:

```
"registry-mirrors":  ["https://mirror.gcr.io", "https://daocloud.io", "https://c.163.com/", "https://registry.docker-cn.com"]
```

run install.sh as root

check node_exporter
```
curl -s localhost:9100/metrics
```

### Install server part

Replace this with your Vast API key 
```
- "--api-key= ... "
```

run install.sh as root


check prometheus metrics
```
curl -s localhost:9090/api/v1/label/__name__/values | jq
```

### Server
* runs prometheus container and stores data from clients
* runs vastai-exporter container to get info about your machines from VAST

https://github.com/alkorolyov/prometheus-vastai
