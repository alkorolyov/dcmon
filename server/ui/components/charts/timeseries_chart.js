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
            hours: 24,
            aggregation: 'max',
            title: options.title || `${metricName} Over Time`,
            yLabel: options.yLabel || 'Value',
            unit: options.unit || '',
            ...options
        };
        
        this.chartManager = window.chartManager;
    }
    
    /**
     * Initialize the chart with optimized settings
     */
    initialize() {
        if (!this.chartManager) {
            throw new Error('ChartManager not available');
        }
        
        // Get or create chart with cache preservation
        this.chartManager.getOrCreateChart(this.containerId, {
            title: this.options.title,
            yLabel: this.options.yLabel,
            unit: this.options.unit,
            apiEndpoint: `/api/timeseries/${this.metricName}`,
            apiParams: {
                hours: this.options.hours,
                aggregation: this.options.aggregation,
                ...(this.options.sensor && { sensor: this.options.sensor })
            }
        });
        
        console.log(`TimeSeriesChart initialized: ${this.metricName}`);
        return true;
    }
    
    /**
     * Refresh the chart data
     */
    refresh() {
        const chartInfo = this.chartManager.getChartInfo(this.containerId);
        if (chartInfo) {
            this.chartManager.loadChartData(this.containerId);
        }
    }
    
    /**
     * Update chart parameters (hours, aggregation, etc.)
     */
    updateParams(newParams) {
        this.options = { ...this.options, ...newParams };
        
        // Get current chart info and update config
        const chartInfo = this.chartManager.getChartInfo(this.containerId);
        if (chartInfo) {
            chartInfo.config.apiParams = {
                hours: this.options.hours,
                aggregation: this.options.aggregation
            };
            
            // Reload with new parameters
            this.chartManager.loadChartData(this.containerId);
        }
    }
    
    /**
     * Destroy the chart
     */
    destroy() {
        if (this.chartManager) {
            this.chartManager.destroyChart(this.containerId);
        }
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
        return new TimeSeriesChart(containerId, 'ipmi_temp_celsius', {
            title: 'CPU Temperature',
            yLabel: 'Temperature', 
            unit: '°C',
            aggregation: 'max',
            sensor: 'CPU'  // Filter to CPU sensors only
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
}

// Export for global usage
window.TimeSeriesChart = TimeSeriesChart;

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TimeSeriesChart;
}