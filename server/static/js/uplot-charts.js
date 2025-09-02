/**
 * uPlot Time Series Chart Manager
 * 
 * Manages multiple time series charts with synchronized zoom/pan and Grafana styling.
 * AI-friendly declarative configuration approach.
 */

class TimeSeriesManager {
    constructor() {
        this.charts = new Map();
        this.globalTimeRange = { start: null, end: null };
        this.isUpdatingRange = false;
        
        // Grafana-style colors from our CSS variables
        this.colors = ["#73bf69", "#f2495c", "#5794f2", "#ff9830", "#9d7bd8", "#70dbed"];
        
        console.log('TimeSeriesManager initialized');
    }
    
    /**
     * Create a new time series chart
     * @param {string} containerId - DOM element ID to contain the chart
     * @param {Object} config - Chart configuration
     * @param {string} config.title - Chart title
     * @param {string} config.yLabel - Y-axis label
     * @param {string} config.unit - Value unit (e.g., "°C", "%", "W")
     * @param {number} config.width - Chart width in pixels
     * @param {number} config.height - Chart height in pixels
     * @param {string} config.apiEndpoint - API endpoint to fetch data from
     * @param {Object} config.apiParams - Additional API parameters
     */
    createChart(containerId, config) {
        const container = document.getElementById(containerId);
        if (!container) {
            console.error(`Container ${containerId} not found`);
            return null;
        }
        
        // Create uPlot configuration with Grafana styling
        const uplotConfig = {
            title: config.title,
            width: config.width || 800,
            height: config.height || 300,
            cursor: {
                sync: {
                    key: 'timeseries-sync' // Sync cursor across all charts
                }
            },
            scales: {
                x: {
                    time: true
                },
                y: {
                    auto: true,
                    range: (u, min, max) => {
                        // Add 5% padding to y-axis range
                        const pad = (max - min) * 0.05;
                        return [min - pad, max + pad];
                    }
                }
            },
            axes: [
                {
                    // X-axis (time)
                    stroke: "#6e7680",
                    grid: { stroke: "#dcdee1", width: 1 },
                    ticks: { stroke: "#6e7680", width: 1 }
                },
                {
                    // Y-axis
                    label: config.yLabel || "Value",
                    labelGap: 12,
                    stroke: "#6e7680",
                    grid: { stroke: "#dcdee1", width: 1 },
                    ticks: { stroke: "#6e7680", width: 1 },
                    values: (u, vals) => vals.map(v => v + (config.unit || ''))
                }
            ],
            series: [
                {} // x-axis series (will be populated with data)
            ],
            hooks: {
                // Sync zoom across all charts
                setScale: [
                    (u, key) => {
                        if (key === 'x' && !this.isUpdatingRange) {
                            const range = u.scales.x;
                            this.syncTimeRange(range.min, range.max);
                        }
                    }
                ]
            },
            legend: {
                live: true,
                show: true
            }
        };
        
        // Store chart config for data loading
        const chartInfo = {
            container: container,
            config: config,
            uplotConfig: uplotConfig,
            chart: null,
            data: null
        };
        
        this.charts.set(containerId, chartInfo);
        
        // Load initial data
        this.loadChartData(containerId);
        
        return chartInfo;
    }
    
    /**
     * Load data for a specific chart from its API endpoint
     */
    async loadChartData(chartId) {
        const chartInfo = this.charts.get(chartId);
        if (!chartInfo) return;
        
        try {
            const config = chartInfo.config;
            let url = config.apiEndpoint;
            
            // Add API parameters
            const params = new URLSearchParams();
            if (config.apiParams) {
                for (const [key, value] of Object.entries(config.apiParams)) {
                    if (Array.isArray(value)) {
                        value.forEach(v => params.append(key, v));
                    } else {
                        params.set(key, value);
                    }
                }
            }
            
            if (params.toString()) {
                url += '?' + params.toString();
            }
            
            console.log(`Loading chart data from: ${url}`);
            
            // Dashboard API inherits authentication - no token needed
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            // Update chart with new data
            this.updateChart(chartId, data);
            
        } catch (error) {
            console.error(`Error loading data for chart ${chartId}:`, error);
            this.showChartError(chartId, error.message);
        }
    }
    
    /**
     * Update a chart with new data
     */
    updateChart(chartId, apiData) {
        const chartInfo = this.charts.get(chartId);
        if (!chartInfo) return;
        
        try {
            // Update uPlot configuration with series from API
            chartInfo.uplotConfig.series = apiData.series;
            
            // Store data
            chartInfo.data = apiData.data;
            
            // Create or update uPlot instance
            if (chartInfo.chart) {
                chartInfo.chart.setData(apiData.data);
            } else {
                chartInfo.chart = new uPlot(
                    chartInfo.uplotConfig,
                    apiData.data,
                    chartInfo.container
                );
            }
            
            console.log(`Chart ${chartId} updated with ${apiData.data[0]?.length || 0} data points`);
            
        } catch (error) {
            console.error(`Error updating chart ${chartId}:`, error);
            this.showChartError(chartId, error.message);
        }
    }
    
    /**
     * Synchronize time range across all charts
     */
    syncTimeRange(start, end) {
        if (this.isUpdatingRange) return;
        
        this.isUpdatingRange = true;
        this.globalTimeRange = { start, end };
        
        // Update all charts with new time range
        for (const [chartId, chartInfo] of this.charts) {
            if (chartInfo.chart && chartInfo.chart.scales.x) {
                chartInfo.chart.setScale('x', { min: start, max: end });
            }
        }
        
        this.isUpdatingRange = false;
        console.log(`Time range synced: ${new Date(start * 1000).toISOString()} to ${new Date(end * 1000).toISOString()}`);
    }
    
    /**
     * Show error message in chart container
     */
    showChartError(chartId, errorMessage) {
        const chartInfo = this.charts.get(chartId);
        if (!chartInfo) return;
        
        chartInfo.container.innerHTML = `
            <div style="
                display: flex;
                align-items: center;
                justify-content: center;
                height: ${chartInfo.uplotConfig.height}px;
                background: #f7f8fa;
                border: 1px solid #dcdee1;
                border-radius: 3px;
                color: #6e7680;
                font-family: Inter, sans-serif;
                font-size: 14px;
            ">
                <div style="text-align: center;">
                    <div style="font-weight: 600; margin-bottom: 8px;">Chart Error</div>
                    <div>${errorMessage}</div>
                </div>
            </div>
        `;
    }
    
    /**
     * Dashboard authentication is handled automatically by browser session.
     * No explicit token management needed for dashboard API endpoints.
     */
    
    /**
     * Refresh all charts
     */
    refreshAll() {
        console.log('Refreshing all charts...');
        for (const chartId of this.charts.keys()) {
            this.loadChartData(chartId);
        }
    }
    
    /**
     * Destroy a chart and clean up resources
     */
    destroyChart(chartId) {
        const chartInfo = this.charts.get(chartId);
        if (!chartInfo) return;
        
        if (chartInfo.chart) {
            chartInfo.chart.destroy();
        }
        
        this.charts.delete(chartId);
        console.log(`Chart ${chartId} destroyed`);
    }
    
    /**
     * Get chart info for debugging
     */
    getChartInfo(chartId) {
        return this.charts.get(chartId);
    }
}

// Create global instance
window.timeSeriesManager = new TimeSeriesManager();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TimeSeriesManager;
}