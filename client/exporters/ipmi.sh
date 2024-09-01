#!/usr//bin/env bash
# Export ipmitool sensor output to prom metrics

# Check if script is run by root
if [ "$(id -u)" -ne 0 ]; then
    echo "This script must be run as root." >&2
    exit 1
fi

# Check if ipmitool is installed
if ! command -v ipmitool &> /dev/null; then
    echo "ipmitool could not be found. Please install ipmitool." >&2
    exit 1
fi

# Run ipmitool sensor and pipe to AWK for processing
ipmitool sensor | awk '
    function export(values, name) {
        if (values["metric_count"] < 1) {
            return
        }
        delete values["metric_count"]

        printf("# HELP %s%s %s sensor reading from ipmitool\n", namespace, name, help[name]);
        printf("# TYPE %s%s gauge\n", namespace, name);
        for (sensor in values) {
            printf("%s%s{sensor=\"%s\"} %f\n", namespace, name, sensor, values[sensor]);
        }
    }

    BEGIN {
        FS = "[ ]*[|][ ]*";
        namespace = "ipmi_";

        # Friendly description of the type of sensor for HELP.
        help["temperature_celsius"] = "Temperature";
        help["volts"] = "Voltage";
        help["amps"] = "Current";
        help["power_watts"] = "Power";
        help["speed_rpm"] = "Fan";
        help["percent"] = "Device";
        help["status"] = "Chassis status";

        temperature_celsius["metric_count"] = 0;
        volts["metric_count"] = 0;
        amps["metric_count"] = 0;
        power_watts["metric_count"] = 0;
        speed_rpm["metric_count"] = 0;
        percent["metric_count"] = 0;
        status["metric_count"] = 0;
    }

    # Not a valid line.
    {
        if (NF < 3) {
            next
        }
    }

    # $2 is value field.
    $2 ~ /na/ {
        next
    }

    # $3 is type field.
    $3 ~ /degrees C/ {
        temperature_celsius[$1] = $2;
        temperature_celsius["metric_count"]++;
    }

    $3 ~ /Volts/ {
        volts[$1] = $2;
        volts["metric_count"]++;
    }

    $3 ~ /Amps/ {
        amps[$1] = $2;
        amps["metric_count"]++;
    }

    $3 ~ /Watts/ {
        power_watts[$1] = $2;
        power_watts["metric_count"]++;
    }

    $3 ~ /RPM/ {
        speed_rpm[$1] = $2;
        speed_rpm["metric_count"]++;
    }

    $3 ~ /percent/ {
            percent[$1] = $2;
            percent["metric_count"]++;
    }

    $3 ~ /discrete/ {
        status[$1] = sprintf("%d", substr($2,3,2));
        status["metric_count"]++;
    }

    END {
        export(temperature_celsius, "temperature_celsius");
        export(volts, "volts");
        export(amps, "amps");
        export(power_watts, "power_watts");
        export(speed_rpm, "speed_rpm");
        export(percent, "percent");
        export(status, "status");
    }
'
