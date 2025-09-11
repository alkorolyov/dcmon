/**
 * Time Series Chart Component
 * 
 * Specific implementation for dcmon timeseries charts (GPU temp, CPU temp, etc.)
 */

class TimeSeriesChart {
    constructor(containerId, metricName, options = {}) {
        this.containerId = containerId;
        this.metricName = metricName;
        this.options = {
            seconds: this.getGlobalTimeRange(),
            aggregation: 'max',
            title: options.title || `${metricName} Over Time`,
            yLabel: options.yLabel || 'Value',
            unit: options.unit || '',
            ...options
        };
        
        this.chartManager = window.chartManager;
    }
    
    /**
     * Get global time range from dashboard controls
     */
    getGlobalTimeRange() {
        return window.dashboardControls.parseTimeRangeToSeconds(window.dashboardControls.currentTimeRange);
    }
    
    /**
     * Initialize the chart with optimized settings
     */
    initialize() {
        if (!this.chartManager) {
            throw new Error('ChartManager not available');
        }
        
        // Get or create chart with cache preservation
        // Handle both single metric name and array of metric names
        const metricNameParam = Array.isArray(this.metricName) 
            ? this.metricName.join(',') 
            : this.metricName;
        
        // Use dedicated rate endpoint for rate calculations
        const isRateChart = this.options.rate;
        const apiEndpoint = isRateChart 
            ? `/api/timeseries/${metricNameParam}/rate`
            : `/api/timeseries/${metricNameParam}`;
            
        // Prepare API parameters based on chart type
        let apiParams = {
            seconds: this.options.seconds,
            aggregation: this.options.aggregation
        };
        
        if (isRateChart) {
            // Rate-specific parameters
            if (this.options.rate_window) apiParams.rate_window = this.options.rate_window;
            if (this.options.labels) apiParams.labels = JSON.stringify(this.options.labels);
        } else {
            // Regular timeseries parameters
            if (this.options.labels) {
                // Multiple sensor labels (JSON array)
                apiParams.labels = JSON.stringify(this.options.labels);
            } else if (this.options.sensor) {
                // Single sensor (backward compatibility)
                apiParams.sensor = this.options.sensor;
            }
        }
            
        this.chartManager.getOrCreateChart(this.containerId, {
            title: this.options.title,
            yLabel: this.options.yLabel,
            unit: this.options.unit,
            apiEndpoint: apiEndpoint,
            apiParams: apiParams
        });
        
        console.log(`TimeSeriesChart initialized: ${this.metricName}`);
        return true;
    }
    
    /**
     * Refresh the chart data
     */
    refresh() {
        this.chartManager.loadChartData(this.containerId);
    }
    
    /**
     * Update chart parameters (hours, aggregation, etc.)
     */
    updateParams(newParams) {
        this.options = { ...this.options, ...newParams };
        
        // Update chart config and reload
        const chartInfo = this.chartManager.getChartInfo(this.containerId);
        chartInfo.config.apiParams = {
            seconds: this.options.seconds,
            aggregation: this.options.aggregation
        };
        
        this.chartManager.loadChartData(this.containerId);
    }
    
    /**
     * Destroy the chart
     */
    destroy() {
        this.chartManager.destroyChart(this.containerId);
    }
    
    /**
     * Static factory methods for common chart types
     */
    static createGpuTempChart(containerId) {
        return new TimeSeriesChart(containerId, 'gpu_temperature', {
            title: 'GPU Temperature',
            yLabel: 'Temperature',
            unit: '°C',
            aggregation: 'max'
        });
    }
    
    static createCpuTempChart(containerId) {
        // Use centralized CPU sensor mapping
        const CPU_SENSORS = [{"sensor": "CPU Temp"}, {"sensor": "TEMP_CPU"}];
        return new TimeSeriesChart(containerId, 'ipmi_temp_celsius', {
            title: 'CPU Temperature',
            yLabel: 'Temperature', 
            unit: '°C',
            aggregation: 'max',
            labels: CPU_SENSORS
        });
    }
    
    static createCpuUsageChart(containerId) {
        return new TimeSeriesChart(containerId, 'cpu_usage_percent', {
            title: 'CPU Usage',
            yLabel: 'Usage',
            unit: '%',
            aggregation: 'avg'
        });
    }
    
    static createMemoryUsageChart(containerId) {
        return new TimeSeriesChart(containerId, 'memory_usage_percent', {
            title: 'Memory Usage',
            yLabel: 'Usage',
            unit: '%',
            aggregation: 'avg'
        });
    }
    
    static createGpuPowerChart(containerId) {
        return new TimeSeriesChart(containerId, 'gpu_power_draw', {
            title: 'GPU Power Draw',
            yLabel: 'Power',
            unit: 'W',
            aggregation: 'avg'
        });
    }
    
    static createDiskUsageChart(containerId) {
        return new TimeSeriesChart(containerId, 'disk_usage_percent', {
            title: 'Disk Usage',
            yLabel: 'Usage',
            unit: '%',
            aggregation: 'avg'
        });
    }
    
    static createGpuFanChart(containerId) {
        return new TimeSeriesChart(containerId, 'gpu_fan_speed', {
            title: 'GPU Fan Speed',
            yLabel: 'Fan Speed',
            unit: '%',
            aggregation: 'max'
        });
    }
    
    static createPsuTempChart(containerId) {
        return new TimeSeriesChart(containerId, ['psu_temp1_celsius', 'psu_temp2_celsius'], {
            title: 'PSU Temperature',
            yLabel: 'Temperature',
            unit: '°C',
            aggregation: 'max'
        });
    }
    
    static createPsuPowerChart(containerId) {
        return new TimeSeriesChart(containerId, 'psu_input_power_watts', {
            title: 'PSU Power',
            yLabel: 'Power',
            unit: 'W',
            aggregation: 'sum'
        });
    }
    
    static createPsuFanChart(containerId) {
        return new TimeSeriesChart(containerId, ['psu_fan1_rpm', 'psu_fan2_rpm'], {
            title: 'PSU Fan Speed',
            yLabel: 'Fan Speed',
            unit: 'RPM',
            aggregation: 'max'
        });
    }
    
    static createNetworkRateChart(containerId) {
        return new TimeSeriesChart(containerId, ['network_receive_bytes_total', 'network_transmit_bytes_total'], {
            title: 'Network Activity',
            yLabel: 'Network Rate',
            unit: 'B/s',
            aggregation: 'sum',
            rate: true,
            rate_window: 5
        });
    }
    
    static createDockerIoChart(containerId) {
        return new TimeSeriesChart(containerId, ['disk_read_bytes_total', 'disk_write_bytes_total'], {
            title: 'Disk I/O Activity', 
            yLabel: 'I/O Rate',
            unit: 'B/s',
            aggregation: 'sum',
            rate: true,
            rate_window: 5
        });
    }
}

// Export for global usage
window.TimeSeriesChart = TimeSeriesChart;

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TimeSeriesChart;
}