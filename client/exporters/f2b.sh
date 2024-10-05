#!/usr/bin/env bash
#
# Description: Expose metrics from fail2ban jails
#
# Author: Alexander Korolyov <korol.al@gmail.com>

# Function to extract metrics from jail status
parse_jail_metrics() {
    jail_name=$1
    status_output=$(fail2ban-client status "$jail_name")

    # Extract metrics from the status output
    currently_failed=$(echo "$status_output" | grep "Currently failed:" | awk '{print $5}')
    total_failed=$(echo "$status_output" | grep "Total failed:" | awk '{print $5}')
    currently_banned=$(echo "$status_output" | grep "Currently banned:" | awk '{print $4}')
    total_banned=$(echo "$status_output" | grep "Total banned:" | awk '{print $4}')

    # Print Prometheus metrics for this jail
    echo "# HELP fail2ban_currently_failed Number of failed connections."
    echo "# TYPE fail2ban_currently_failed counter"
    echo "fail2ban_currently_failed{jail=\"$jail_name\"} $currently_failed"

    echo "# HELP fail2ban_total_failed Number of all time failed connections."
    echo "# TYPE fail2ban_total_failed counter"
    echo "fail2ban_total_failed{jail=\"$jail_name\"} $total_failed"

    echo "# HELP fail2ban_currently_banned Number of banned IP-Addresses in the timeframe."
    echo "# TYPE fail2ban_currently_banned counter"
    echo "fail2ban_currently_banned{jail=\"$jail_name\"} $currently_banned"

    echo "# HELP fail2ban_total_banned Number of all time banned IP-Addresses."
    echo "# TYPE fail2ban_total_banned counter"
    echo "fail2ban_total_banned{jail=\"$jail_name\"} $total_banned"
}

# Check if we are root
if [ "$EUID" -ne 0 ]; then
  echo "${0##*/}: Please run as root!" >&2
  exit 1
fi

# Check if fail2ban is running
if ! systemctl is-active --quiet fail2ban; then
#  echo "${0##*/}: fail2ban is not running. Aborting." >&2
  exit 0
fi

# Get the status of fail2ban and extract the number of jails and list of jails
status_output=$(fail2ban-client status)
num_jails=$(echo "$status_output" | grep "Number of jail:" | awk '{print $5}')
jail_list=$(echo "$status_output" | grep "Jail list:" | cut -d ':' -f2 | tr ',' ' ')

# Print the total number of jails as a Prometheus metric
echo "# HELP fail2ban_jails_total Total number of jails."
echo "# TYPE fail2ban_jails_total gauge"
echo "fail2ban_jails_total $num_jails"

# Loop through each jail and parse its metrics
for jail in $jail_list; do
    parse_jail_metrics "$jail"
done
