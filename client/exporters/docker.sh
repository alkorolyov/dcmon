#!/usr/bin/env bash
#
# Description: Expose metrics from docker stats
#
# Author: Alexander Korolyov <korol.al@gmail.com>

# Function to convert memory or IO values to bytes
convert_to_bytes() {
    local input=$1
    local value=$(echo "$input" | sed 's/[A-Za-z]//g')
    # strip 'i' and normalize to upper letters
    local unit=$(echo "$input" | sed 's/[0-9.i]//g' | tr '[:lower:]' '[:upper:]')

    case "$unit" in
        B) echo "${value}";;
        KB) echo "$(echo "${value} * 1024" | bc | awk '{printf "%.0f", $0}')";;
        MB) echo "$(echo "${value} * 1024 * 1024" | bc | awk '{printf "%.0f", $0}')";;
        GB) echo "$(echo "${value} * 1024 * 1024 * 1024" | bc | awk '{printf "%.0f", $0}')";;
        TB) echo "$(echo "${value} * 1024 * 1024 * 1024 * 1024" | bc | awk '{printf "%.0f", $0}')";;
        PB) echo "$(echo "${value} * 1024 * 1024 * 1024 * 1024 * 1024" | bc | awk '{printf "%.0f", $0}')";;
        *) echo "Unsupported unit: $unit" >&2; exit 1;;
    esac
}

# Print HELP and TYPE information for each metric (only once)
echo "# HELP docker_container_cpu_percentage CPU usage percentage of the container"
echo "# TYPE docker_container_cpu_percentage gauge"
echo "# HELP docker_container_memory_usage_bytes Memory usage of the container in bytes"
echo "# TYPE docker_container_memory_usage_bytes gauge"
echo "# HELP docker_container_memory_limit_bytes Memory limit of the container in bytes"
echo "# TYPE docker_container_memory_limit_bytes gauge"
echo "# HELP docker_container_memory_percentage Memory usage percentage of the container"
echo "# TYPE docker_container_memory_percentage gauge"
echo "# HELP docker_container_network_receive_bytes Network receive bytes by the container"
echo "# TYPE docker_container_network_receive_bytes counter"
echo "# HELP docker_container_network_transmit_bytes Network transmit bytes by the container"
echo "# TYPE docker_container_network_transmit_bytes counter"
echo "# HELP docker_container_block_io_read_bytes Block I/O read bytes by the container"
echo "# TYPE docker_container_block_io_read_bytes counter"
echo "# HELP docker_container_block_io_write_bytes Block I/O write bytes by the container"
echo "# TYPE docker_container_block_io_write_bytes counter"
echo "# HELP docker_container_pids Number of processes or threads in the container"
echo "# TYPE docker_container_pids gauge"

# Run docker stats command and capture the output
docker stats --no-stream --format "{{.ID}} {{.Name}} {{.CPUPerc}} {{.MemUsage}} {{.MemPerc}} {{.NetIO}} {{.BlockIO}} {{.PIDs}}" | while read -r line; do
    # Parse each line of the docker stats output
    CONTAINER_ID=$(echo $line | awk '{print $1}')
    NAME=$(echo $line | awk '{print $2}')
    CPU=$(echo $line | awk '{print $3}' | sed 's/%//')
    MEM_USAGE=$(echo $line | awk '{print $4}')
    MEM_LIMIT=$(echo $line | awk '{print $6}' )
    MEM_PERC=$(echo $line | awk '{print $7}' | sed 's/%//')
    NET_IO_RX=$(echo $line | awk '{print $8}')
    NET_IO_TX=$(echo $line | awk '{print $10}')
    BLOCK_IO_READ=$(echo $line | awk '{print $11}')
    BLOCK_IO_WRITE=$(echo $line | awk '{print $13}')
    PIDS=$(echo $line | awk '{print $14}')

    MEM_USAGE_BYTES=$(convert_to_bytes $MEM_USAGE)
    MEM_LIMIT_BYTES=$(convert_to_bytes $MEM_LIMIT)
    NET_IO_RX_BYTES=$(convert_to_bytes $NET_IO_RX)
    NET_IO_TX_BYTES=$(convert_to_bytes $NET_IO_TX)
    BLOCK_IO_READ_BYTES=$(convert_to_bytes $BLOCK_IO_READ)
    BLOCK_IO_WRITE_BYTES=$(convert_to_bytes $BLOCK_IO_WRITE)

    # Output metrics in Prometheus format without HELP and TYPE lines
    echo "docker_container_cpu_percentage{name=\"$NAME\",id=\"$CONTAINER_ID\"} $CPU"
    echo "docker_container_memory_usage_bytes{name=\"$NAME\",id=\"$CONTAINER_ID\"} $MEM_USAGE_BYTES"
    echo "docker_container_memory_limit_bytes{name=\"$NAME\",id=\"$CONTAINER_ID\"} $MEM_LIMIT_BYTES"
    echo "docker_container_memory_percentage{name=\"$NAME\",id=\"$CONTAINER_ID\"} $MEM_PERC"
    echo "docker_container_network_receive_bytes{name=\"$NAME\",id=\"$CONTAINER_ID\"} $NET_IO_RX_BYTES"
    echo "docker_container_network_transmit_bytes{name=\"$NAME\",id=\"$CONTAINER_ID\"} $NET_IO_TX_BYTES"
    echo "docker_container_block_io_read_bytes{name=\"$NAME\",id=\"$CONTAINER_ID\"} $BLOCK_IO_READ_BYTES"
    echo "docker_container_block_io_write_bytes{name=\"$NAME\",id=\"$CONTAINER_ID\"} $BLOCK_IO_WRITE_BYTES"
    echo "docker_container_pids{name=\"$NAME\",id=\"$CONTAINER_ID\"} $PIDS"
done
