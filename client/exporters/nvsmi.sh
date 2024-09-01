#!/usr/bin/env bash

# Print Prometheus metrics header
echo "# HELP gpu_ecc_errors_corrected Total number of ECC errors corrected"
echo "# TYPE gpu_ecc_errors_corrected counter"
echo "# HELP gpu_ecc_errors_uncorrected Total number of ECC errors uncorrected"
echo "# TYPE gpu_ecc_errors_uncorrected counter"
echo "# HELP gpu_temperature GPU temperature in degrees Celsius"
echo "# TYPE gpu_temperature gauge"
echo "# HELP gpu_power_draw GPU power draw in watts"
echo "# TYPE gpu_power_draw gauge"
echo "# HELP gpu_power_limit GPU power limit in watts"
echo "# TYPE gpu_power_limit gauge"
echo "# HELP gpu_utilization_gpu Percent of time over the past sample period during which one or more kernels was executing on the GPU"
echo "# TYPE gpu_utilization_gpu gauge"
echo "# HELP gpu_utilization_memory Percent of time over the past sample period during which global (device) memory was being read or written"
echo "# TYPE gpu_utilization_memory gauge"
echo "# HELP gpu_fan_speed Fan speed percentage"
echo "# TYPE gpu_fan_speed gauge"
echo "# HELP gpu_clock_sm SM clock speed in MHz"
echo "# TYPE gpu_clock_sm gauge"
echo "# HELP gpu_clock_mem Memory clock speed in MHz"
echo "# TYPE gpu_clock_mem gauge"
echo "# HELP gpu_pcie_gen PCIe link generation"
echo "# TYPE gpu_pcie_gen gauge"
echo "# HELP gpu_pcie_width PCIe link width"
echo "# TYPE gpu_pcie_width gauge"
echo "# HELP gpu_pstate GPU performance state"
echo "# TYPE gpu_pstate gauge"
echo "# HELP gpu_ecc_mode_current Current ECC mode"
echo "# TYPE gpu_ecc_mode_current gauge"
echo "# HELP gpu_ecc_mode_pending Pending ECC mode"
echo "# TYPE gpu_ecc_mode_pending gauge"
echo "# HELP gpu_memory_usage Percentage of total memory in use"
echo "# TYPE gpu_memory_usage gauge"

# Query NVIDIA GPU metrics including GPU name
output=$(nvidia-smi --query-gpu=gpu_bus_id,pcie.link.gen.current,pcie.link.width.current,fan.speed,pstate,utilization.gpu,utilization.memory,ecc.mode.current,ecc.mode.pending,ecc.errors.uncorrected.aggregate.total,ecc.errors.corrected.aggregate.total,temperature.gpu,power.draw,power.limit,clocks.sm,clocks.mem,memory.total,memory.reserved,memory.used,name --format=csv,noheader)

# Read the output line by line
while IFS=',' read -r pci_bus_id pcie_gen pcie_width fan_speed pstate gpu_util mem_util ecc_mode_current ecc_mode_pending ecc_errors_uncorrected ecc_errors_corrected temp_gpu power_draw power_limit clocks_sm clocks_mem memory_total memory_reserved memory_used name; do

    # Sanitize GPU name for Prometheus label
    name=$(echo "$name" | awk '{print $(NF-1), $NF}')
    pci_bus_id=$(echo "$pci_bus_id" | awk -F':' '{print $(NF-1)":"$NF}')

    # Define the label format
    gpu_label="model=\"$name\",bus_id=\"$pci_bus_id\""

    # Remove percentage signs and extra characters
    fan_speed=$(echo "$fan_speed" | tr -d ' %')
    gpu_util=$(echo "$gpu_util" | tr -d ' %')
    mem_util=$(echo "$mem_util" | tr -d ' %')
    temp_gpu=$(echo "$temp_gpu" | tr -d ' ')
    power_draw=$(echo "$power_draw" | tr -d ' W')
    power_limit=$(echo "$power_limit" | tr -d ' W')
    clocks_sm=$(echo "$clocks_sm" | tr -d ' MHz')
    clocks_mem=$(echo "$clocks_mem" | tr -d ' MHz')
    memory_total=$(echo "$memory_total" | tr -d ' MiB')
    memory_reserved=$(echo "$memory_reserved" | tr -d ' MiB')
    memory_used=$(echo "$memory_used" | tr -d ' MiB')

    # Handle other columns
    pcie_gen=$(echo "$pcie_gen" | tr -d ' ')
    pcie_width=$(echo "$pcie_width" | tr -d ' ')
    pstate=$(echo "$pstate" | tr -d ' ' | sed 's/P//')
    ecc_mode_current=$(echo "$ecc_mode_current" | tr -d ' ')
    ecc_mode_pending=$(echo "$ecc_mode_pending" | tr -d ' ')
    ecc_errors_corrected=$(echo "$ecc_errors_corrected" | tr -d ' ')
    ecc_errors_uncorrected=$(echo "$ecc_errors_uncorrected" | tr -d ' ')

    # Convert ECC modes to boolean
    ecc_mode_current=$( [[ "$ecc_mode_current" == "Enabled" ]] && echo 1 || echo 0 )
    ecc_mode_pending=$( [[ "$ecc_mode_pending" == "Enabled" ]] && echo 1 || echo 0 )

    # Calculate the total memory in use (reserved + used)
    total_memory_in_use=$((memory_reserved + memory_used))

    # Calculate the percentage of total memory in use and round to 2 decimal places
    memory_usage_percentage=$(awk "BEGIN {printf \"%.2f\", ($total_memory_in_use/$memory_total)*100}")

    # Print Prometheus metrics
    if [[ "$ecc_errors_corrected" != "[N/A]" ]]; then
        echo "gpu_ecc_errors_corrected{$gpu_label} $ecc_errors_corrected"
    fi

    if [[ "$ecc_errors_uncorrected" != "[N/A]" ]]; then
        echo "gpu_ecc_errors_uncorrected{$gpu_label} $ecc_errors_uncorrected"
    fi

    echo "gpu_temperature{$gpu_label} $temp_gpu"
    echo "gpu_power_draw{$gpu_label} $power_draw"
    echo "gpu_power_limit{$gpu_label} $power_limit"
    echo "gpu_utilization_gpu{$gpu_label} $gpu_util"
    echo "gpu_utilization_memory{$gpu_label} $mem_util"
    echo "gpu_fan_speed{$gpu_label} $fan_speed"
    echo "gpu_clock_sm{$gpu_label} $clocks_sm"
    echo "gpu_clock_mem{$gpu_label} $clocks_mem"
    echo "gpu_pcie_gen{$gpu_label} $pcie_gen"
    echo "gpu_pcie_width{$gpu_label} $pcie_width"
    echo "gpu_pstate{$gpu_label} $pstate"
    echo "gpu_ecc_mode_current{$gpu_label} $ecc_mode_current"
    echo "gpu_ecc_mode_pending{$gpu_label} $ecc_mode_pending"
    echo "gpu_memory_usage{$gpu_label} $memory_usage_percentage"

done <<< "$output"
