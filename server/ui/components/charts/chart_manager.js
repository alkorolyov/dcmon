/**
 * Chart Manager - Time Series Chart Management for dcmon Dashboard
 * 
 * AI-friendly modular chart system with synchronized zoom/pan and responsive layout.
 * Optimized for two charts per row with thinner plot lines.
 */

// Chart configuration constants - Single source of truth for UI dimensions
const CHART_DEFAULTS = {
    PLOT_HEIGHT: 200,      // Actual plot area height (compact size for efficient dashboard layout)
    LEGEND_HEIGHT: 32,     // Space for legend (optimized with uPlot axis configuration + increased bottom padding)
    TITLE_HEIGHT: 18,      // Small space for title above plot
    PADDING: 6,           // Reduced container padding
    get TOTAL_HEIGHT() {   // Total container height (title + plot + legend)
        return this.PLOT_HEIGHT + this.LEGEND_HEIGHT + this.TITLE_HEIGHT;
    },
    MIN_WIDTH: 400        // Minimum chart width
};

// Set CSS custom properties for styling consistency
if (typeof document !== 'undefined') {
    document.documentElement.style.setProperty('--chart-total-height', CHART_DEFAULTS.TOTAL_HEIGHT + 'px');
    document.documentElement.style.setProperty('--chart-plot-height', CHART_DEFAULTS.PLOT_HEIGHT + 'px');
    document.documentElement.style.setProperty('--chart-legend-height', CHART_DEFAULTS.LEGEND_HEIGHT + 'px');
    document.documentElement.style.setProperty('--chart-padding', CHART_DEFAULTS.PADDING + 'px');
    document.documentElement.style.setProperty('--chart-min-width', CHART_DEFAULTS.MIN_WIDTH + 'px');
}

class ChartManager {
    constructor() {
        this.charts = new Map();
        this.globalTimeRange = { start: null, end: null };
        this.isUpdatingRange = false;
        
        // Grafana-style colors
        this.colors = ["#73bf69", "#f2495c", "#5794f2", "#ff9830", "#9d7bd8", "#70dbed"];
        
        console.log('ChartManager initialized');
    }
    
    /**
     * Create a new time series chart optimized for two-per-row layout
     * @param {string} containerId - DOM element ID to contain the chart
     * @param {Object} config - Chart configuration
     * @param {string} config.title - Chart title
     * @param {string} config.yLabel - Y-axis label
     * @param {string} config.unit - Value unit (e.g., "°C", "%", "W")
     * @param {string} config.apiEndpoint - API endpoint to fetch data from
     * @param {Object} config.apiParams - Additional API parameters
     */
    /**
     * Get or create chart - ensures single instance per container
     */
    getOrCreateChart(containerId, config) {
        if (this.charts.has(containerId)) {
            return this.charts.get(containerId);
        }
        
        return this.createChart(containerId, config);
    }
    
    /**
     * Internal chart creation - only called once per container
     */
    createChart(containerId, config) {
        const container = document.getElementById(containerId);
        if (!container) {
            throw new Error(`Container ${containerId} not found`);
        }
        
        if (this.charts.has(containerId)) {
            throw new Error(`Chart ${containerId} already exists`);
        }
        
        // Calculate width for two-chart layout
        const containerRect = container.getBoundingClientRect();
        let chartWidth = Math.max(400, containerRect.width - 24); // Account for padding
        
        if (chartWidth <= 24) {
            throw new Error(`Container ${containerId} has no width - not rendered yet`);
        }
        
        // Create uPlot configuration with optimized settings
        const uplotConfig = {
            title: config.title,
            width: chartWidth,
            height: CHART_DEFAULTS.PLOT_HEIGHT,
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
                    // X-axis (time) - Optimized spacing with Grafana-style time-only labels
                    size: 20,        // Reduce axis area from default ~25px to 20px
                    gap: 2,          // Small gap between axis labels and axis line
                    ticks: { size: 0 }, // Remove tick marks for cleaner look and space saving
                    stroke: "#6e7680",
                    grid: { stroke: "#dcdee1", width: 1 },
                    values: (u, vals) => vals.map(v => {
                        const date = new Date(v * 1000);
                        return date.toLocaleTimeString('en-US', { 
                            hour12: false, 
                            hour: '2-digit', 
                            minute: '2-digit' 
                        });
                    })
                },
                {
                    // Y-axis (no label - title has the info)
                    size: 70,        // Increased from default to fit labels like "6000RPM"
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
        
        // Store chart config for data loading with smart caching
        const chartInfo = {
            id: containerId,  // ✅ FIX: Add missing chart ID for proper cache tracking
            container: container,
            config: config,
            uplotConfig: uplotConfig,
            chart: null,
            data: null,
            // Smart caching properties
            cachedData: null,
            cachedTimeRange: { start: null, end: null },
            lastRefreshTime: null,
            isAutoRefreshing: false
        };
        
        this.charts.set(containerId, chartInfo);
        
        // Load initial data
        this.loadChartData(containerId);
        
        return chartInfo;
    }
    
    /**
     * Smart data loading with caching and incremental updates
     */
    async loadChartData(chartId, options = {}) {
        const chartInfo = this.charts.get(chartId);
        if (!chartInfo) return;
        
        const { 
            forceFullRefresh = false,
            timeRange = null,
            isAutoRefresh = false 
        } = options;
        
        // Determine what data to fetch
        const queryParams = this.determineQueryParams(chartInfo, timeRange, isAutoRefresh, forceFullRefresh);
        
        if (!queryParams) {
            // No query needed, use cached data
            console.log(`Using cached data for ${chartId}`);
            return;
        }
        
        // Show loading state only for initial loads
        if (!chartInfo.cachedData) {
            this.showChartLoading(chartId);
        }
        
        try {
            const url = this.buildApiUrl(chartInfo.config, queryParams);
            
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const newData = await response.json();
            
            // Merge new data with cached data intelligently
            const mergedData = this.mergeChartData(chartInfo, newData, queryParams);
            
            // Update chart with merged data
            this.updateChart(chartId, mergedData);
            
        } catch (error) {
            console.error(`Error loading data for chart ${chartId}:`, error);
            this.showChartError(chartId, error.message);
        }
    }
    
    /**
     * Determine what query parameters are needed based on cache state
     */
    determineQueryParams(chartInfo, timeRange, isAutoRefresh, forceFullRefresh) {
        const now = Math.floor(Date.now() / 1000);
        
        
        if (forceFullRefresh || !chartInfo.cachedData) {
            // Initial load or forced refresh - get full time range
            const hours = timeRange?.hours || chartInfo.config.apiParams?.hours || 24;
            return {
                type: 'full',
                hours: hours,
                active_only: true
            };
        }
        
        if (isAutoRefresh) {
            // Auto refresh - get only new data since last refresh
            const sinceTimestamp = chartInfo.lastRefreshTime || (now - 300); // Last 5 mins as fallback
            return {
                type: 'incremental',
                since_timestamp: sinceTimestamp,
                active_only: true
            };
        }
        
        if (timeRange) {
            // Time range changed - check if we need more data
            const requestedStart = now - (timeRange.hours * 3600);
            const requestedEnd = now;
            
            if (!chartInfo.cachedTimeRange.start || requestedStart < chartInfo.cachedTimeRange.start) {
                // Need older data
                return {
                    type: 'gap-fill',
                    since_timestamp: requestedStart,
                    until_timestamp: chartInfo.cachedTimeRange.start || requestedEnd,
                    active_only: true
                };
            }
        }
        
        // No query needed - use cached data
        return null;
    }
    
    /**
     * Build API URL with smart parameters
     */
    buildApiUrl(config, queryParams) {
        let url = config.apiEndpoint;
        const params = new URLSearchParams();
        
        // Add base config params
        if (config.apiParams) {
            for (const [key, value] of Object.entries(config.apiParams)) {
                if (key !== 'hours') { // Don't include hours for incremental queries
                    params.set(key, value);
                }
            }
        }
        
        // Add smart query params
        for (const [key, value] of Object.entries(queryParams)) {
            if (key !== 'type') { // Don't send the 'type' param to API
                params.set(key, value);
            }
        }
        
        return url + '?' + params.toString();
    }
    
    /**
     * Merge new data with cached data intelligently
     */
    mergeChartData(chartInfo, newData, queryParams) {
        const now = Math.floor(Date.now() / 1000);
        
        if (queryParams.type === 'full' || !chartInfo.cachedData) {
            // Full refresh or initial load
            chartInfo.cachedData = newData;
            // Calculate time range from the new simplified data format
            let allTimestamps = [];
            Object.values(newData.data).forEach(clientPoints => {
                clientPoints.forEach(point => allTimestamps.push(point.timestamp));
            });
            if (allTimestamps.length > 0) {
                chartInfo.cachedTimeRange = {
                    start: Math.min(...allTimestamps),
                    end: Math.max(...allTimestamps)
                };
            } else {
                chartInfo.cachedTimeRange = { start: now - 86400, end: now };
            }
        } else if (queryParams.type === 'incremental') {
            // Append new data and trim old data
            this.appendAndTrimDataSimplified(chartInfo, newData, queryParams);
        } else if (queryParams.type === 'gap-fill') {
            // Prepend older data
            this.prependDataSimplified(chartInfo, newData);
        }
        
        chartInfo.lastRefreshTime = now;
        return chartInfo.cachedData;
    }
    
    /**
     * Append new data and trim data outside time window (simplified format)
     */
    appendAndTrimDataSimplified(chartInfo, newData, queryParams) {
        if (!newData.data || Object.keys(newData.data).length === 0) return;
        
        // Get latest timestamps from cached data
        let lastCachedTime = 0;
        Object.values(chartInfo.cachedData.data).forEach(clientPoints => {
            clientPoints.forEach(point => {
                if (point.timestamp > lastCachedTime) {
                    lastCachedTime = point.timestamp;
                }
            });
        });
        
        // Merge new data for each client
        Object.entries(newData.data).forEach(([clientId, newPoints]) => {
            if (!chartInfo.cachedData.data[clientId]) {
                chartInfo.cachedData.data[clientId] = [];
            }
            
            // Only append points newer than cached data
            const newerPoints = newPoints.filter(point => point.timestamp > lastCachedTime);
            chartInfo.cachedData.data[clientId].push(...newerPoints);
        });
        
        // Update time range
        let allTimestamps = [];
        Object.values(chartInfo.cachedData.data).forEach(clientPoints => {
            clientPoints.forEach(point => allTimestamps.push(point.timestamp));
        });
        if (allTimestamps.length > 0) {
            chartInfo.cachedTimeRange.end = Math.max(...allTimestamps);
        }
    }
    
    /**
     * Prepend older data for gap filling (simplified format)
     */
    prependDataSimplified(chartInfo, newData) {
        if (!newData.data || Object.keys(newData.data).length === 0) return;
        
        // Merge older data for each client
        Object.entries(newData.data).forEach(([clientId, newPoints]) => {
            if (!chartInfo.cachedData.data[clientId]) {
                chartInfo.cachedData.data[clientId] = [];
            }
            
            // Prepend older data
            chartInfo.cachedData.data[clientId] = [
                ...newPoints,
                ...chartInfo.cachedData.data[clientId]
            ];
        });
        
        // Update time range
        let allTimestamps = [];
        Object.values(newData.data).forEach(clientPoints => {
            clientPoints.forEach(point => allTimestamps.push(point.timestamp));
        });
        if (allTimestamps.length > 0) {
            chartInfo.cachedTimeRange.start = Math.min(...allTimestamps);
        }
    }
    
    /**
     * Prepare uPlot data format from simplified backend response
     */
    prepareUplotData(backendData) {
        if (!backendData.data || Object.keys(backendData.data).length === 0) {
            return { data: [[]], series: [{}], clients: {} };
        }
        
        // Collect all unique timestamps across all clients
        const allTimestamps = new Set();
        Object.values(backendData.data).forEach(clientPoints => {
            clientPoints.forEach(point => allTimestamps.add(point.timestamp));
        });
        
        // Sort timestamps for x-axis
        const sortedTimestamps = Array.from(allTimestamps).sort((a, b) => a - b);
        
        // Initialize uPlot data structure
        const uplotData = [sortedTimestamps]; // x-axis
        const seriesConfig = [{}]; // x-axis config (empty)
        
        // Process each client's data
        let colorIndex = 0;
        for (const [clientId, clientPoints] of Object.entries(backendData.data)) {
            // Create a map of timestamp -> value for this client
            const pointMap = new Map(clientPoints.map(p => [p.timestamp, p.value]));
            
            // Create synchronized series with nulls for missing timestamps
            const series = sortedTimestamps.map(timestamp => pointMap.get(timestamp) ?? null);
            uplotData.push(series);
            
            // Add series configuration
            seriesConfig.push({
                label: backendData.clients[clientId] || `Client ${clientId}`,
                stroke: this.colors[colorIndex % this.colors.length],
                width: 1, // THINNER LINES
                show: true,
                spanGaps: true // Connect lines across missing data points
            });
            colorIndex++;
        }
        
        return {
            data: uplotData,
            series: seriesConfig,
            clients: backendData.clients
        };
    }

    /**
     * Update a chart with new data and apply thinner line styling
     */
    updateChart(chartId, backendData) {
        const chartInfo = this.charts.get(chartId);
        if (!chartInfo) return;
        
        try {
            // Convert backend data to uPlot format
            const uplotData = this.prepareUplotData(backendData);
            
            // Update uPlot configuration with prepared series
            chartInfo.uplotConfig.series = uplotData.series;
            
            // Store uPlot data
            chartInfo.data = uplotData.data;
            
            // Create or update uPlot instance
            if (chartInfo.chart) {
                chartInfo.chart.setData(uplotData.data);
                console.log(`Chart ${chartId} updated with existing uPlot instance`);
            } else {
                // The container IS the chart-content element (template has id="{{ chart_id }}" on chart-content div)
                const targetElement = chartInfo.container;
                
                console.log(`Creating new uPlot chart for ${chartId}:`, {
                    target: targetElement,
                    targetSize: { width: targetElement.offsetWidth, height: targetElement.offsetHeight },
                    config: chartInfo.uplotConfig,
                    dataPoints: uplotData.data[0]?.length || 0
                });
                
                try {
                    chartInfo.chart = new uPlot(
                        chartInfo.uplotConfig,
                        uplotData.data,
                        targetElement
                    );
                    
                    console.log(`uPlot chart created for ${chartId}:`, {
                        chartObject: chartInfo.chart,
                        canvasSize: { 
                            width: chartInfo.chart.over?.offsetWidth, 
                            height: chartInfo.chart.over?.offsetHeight 
                        }
                    });
                } catch (error) {
                    console.error(`Failed to create uPlot chart for ${chartId}:`, error);
                    this.showChartError(chartId, `Chart creation failed: ${error.message}`);
                    return;
                }
            }
            
            // Hide loading/error states
            this.hideChartStates(chartId);
            
            console.log(`Chart ${chartId} updated with ${uplotData.data[0]?.length || 0} data points`);
            
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
        
        // Hide loading state
        const loadingEl = document.getElementById(`${chartId}-loading`);
        if (loadingEl) loadingEl.classList.add('hidden');
        
        // Show error state
        const errorEl = document.getElementById(`${chartId}-error`);
        const errorMessageEl = document.getElementById(`${chartId}-error-message`);
        
        if (errorEl) errorEl.classList.remove('hidden');
        if (errorMessageEl) errorMessageEl.textContent = errorMessage;
        
        console.error(`Chart ${chartId} error:`, errorMessage);
    }
    
    /**
     * Show loading state for chart
     */
    showChartLoading(chartId) {
        // Hide error state
        const errorEl = document.getElementById(`${chartId}-error`);
        if (errorEl) errorEl.classList.add('hidden');
        
        // Show loading state
        const loadingEl = document.getElementById(`${chartId}-loading`);
        if (loadingEl) loadingEl.classList.remove('hidden');
    }
    
    /**
     * Hide loading and error states (chart loaded successfully)
     */
    hideChartStates(chartId) {
        const loadingEl = document.getElementById(`${chartId}-loading`);
        const errorEl = document.getElementById(`${chartId}-error`);
        const chartContent = document.getElementById(`${chartId}`);
        
        if (loadingEl) loadingEl.classList.add('hidden');
        if (errorEl) errorEl.classList.add('hidden');
        
        // Ensure chart content is visible
        if (chartContent) {
            chartContent.classList.remove('hidden');
            chartContent.style.display = 'block';
        }
    }
    
    /**
     * Refresh all charts with smart caching
     */
    refreshAll(isAutoRefresh = false) {        
        for (const chartId of this.charts.keys()) {
            this.loadChartData(chartId, { isAutoRefresh });
        }
    }
    
    /**
     * Update time range for all charts with smart query optimization
     */
    updateTimeRange(seconds) {
        console.log(`Updating time range to ${this.formatSecondsHuman(seconds)} for all charts`);
        
        for (const chartId of this.charts.keys()) {
            const chartInfo = this.charts.get(chartId);
            
            // Update chart config with new seconds
            chartInfo.config.apiParams.seconds = seconds;
            
            // Debug what we have
            console.log(`Chart ${chartId}: cachedData=${!!chartInfo.cachedData}, uplotInstance=${!!chartInfo.chart}`);
            
            // Try cached filtering first, fallback to API call
            if (chartInfo.cachedData && chartInfo.chart) {
                console.log(`Using cached data for ${chartId}`);
                this.filterAndRenderCachedData(chartId, chartInfo, seconds);
            } else {
                console.log(`Loading fresh data for ${chartId}`);
                this.loadChartData(chartId, { type: 'full', timeRange: { seconds } });
            }
        }
    }
    
    /**
     * Format seconds to human readable format
     */
    formatSecondsHuman(seconds) {
        if (seconds < 3600) {
            return `${seconds / 60} min`;
        } else if (seconds < 86400) {
            return `${seconds / 3600} hours`;
        } else {
            return `${seconds / 86400} days`;
        }
    }
    
    /**
     * Filter cached data to new time range and re-render chart
     */
    filterAndRenderCachedData(chartId, chartInfo, seconds) {
        const now = Math.floor(Date.now() / 1000);
        const startTime = now - seconds;
        
        // Always filter from original full cached data, not previously filtered data
        const filteredData = { 
            ...chartInfo.cachedData,
            data: {}
        };
        
        Object.keys(chartInfo.cachedData.data).forEach(clientId => {
            filteredData.data[clientId] = chartInfo.cachedData.data[clientId].filter(
                point => point.timestamp >= startTime
            );
        });
        
        console.log(`Filtered from ${Object.values(chartInfo.cachedData.data).reduce((sum, arr) => sum + arr.length, 0)} to ${Object.values(filteredData.data).reduce((sum, arr) => sum + arr.length, 0)} points`);
        
        // Convert and re-render chart
        const uplotData = this.prepareUplotData(filteredData);
        chartInfo.chart.setData(uplotData.data);
        
        // Force x-axis to rescale to new time range
        if (uplotData.data[0] && uplotData.data[0].length > 0) {
            const minTime = Math.min(...uplotData.data[0]);
            const maxTime = Math.max(...uplotData.data[0]);
            chartInfo.chart.setScale('x', { min: minTime, max: maxTime });
        }
        
        console.log(`Chart ${chartId} re-rendered with filtered data for ${seconds} seconds`);
    }
    
    /**
     * Force full refresh of all charts (clear cache)
     */
    forceRefreshAll() {
        console.log('Force refreshing all charts (clearing cache)...');
        for (const [chartId, chartInfo] of this.charts) {
            // Clear cache
            chartInfo.cachedData = null;
            chartInfo.cachedTimeRange = { start: null, end: null };
            chartInfo.lastRefreshTime = null;
            
            this.loadChartData(chartId, { forceFullRefresh: true });
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
     * Handle window resize - update chart widths for responsive design
     */
    handleResize() {
        for (const [chartId, chartInfo] of this.charts) {
            if (chartInfo.chart && chartInfo.container) {
                const containerRect = chartInfo.container.getBoundingClientRect();
                const newWidth = Math.max(400, containerRect.width - 24);
                
                // Update chart size
                chartInfo.chart.setSize({
                    width: newWidth,
                    height: 300
                });
            }
        }
    }
    
    /**
     * Get chart info for debugging
     */
    getChartInfo(chartId) {
        return this.charts.get(chartId);
    }
}

// Singleton pattern - create once only
if (window.chartManager) {
    throw new Error('ChartManager already exists - singleton violation');
}
window.chartManager = new ChartManager();

// Handle window resize for responsive charts
window.addEventListener('resize', () => {
    window.chartManager.handleResize();
});

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ChartManager;
}