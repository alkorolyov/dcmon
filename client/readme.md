check node_exporter
```
curl -s localhost:9100/metrics
```



node_exporter run command

```
./node_exporter --collector.disable-defaults --collector.cpu --collector.diskstats --collector.filesystem --collector.netdev --collector.meminfo --collector.mdadm --collector.textfile --collector.textfile.directory .
```

