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


check prometheus metrics names
```
curl -s localhost:9090/api/v1/label/__name__/values | jq
```
check single metrics value
```
curl -s localhost:9090/api/v1/query?query=scrape_duration_seconds | jq
```



### Server
* runs prometheus container and stores data from clients
* runs vastai-exporter container to get info about your machines from VAST

https://github.com/alkorolyov/prometheus-vastai
