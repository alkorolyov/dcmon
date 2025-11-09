/**
 * State Timeline Component
 *
 * Grafana-style state timeline visualization showing horizontal lanes for each client
 * with colored state periods (e.g., VastAI rental status over time)
 */

class StateTimeline {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.options = {
            metricName: options.metricName || 'vast_rentals_ondemand',
            title: options.title || 'VastAI Rental Status',
            height: options.height || 200, // Match uPlot charts
            laneHeight: options.laneHeight || 24,
            laneGap: options.laneGap || 4,
            colors: options.colors || {
                0: '#dc3545',      // Red for not rented (value = 0)
                1: '#28a745'       // Green for rented (value > 0)
            },
            stateLabels: options.stateLabels || {
                0: 'Not Rented',
                1: 'Rented'
            },
            ...options
        };

        this.container = null;
        this.canvas = null;
        this.ctx = null;
        this.data = null;
        this.clients = {};
        this.tooltip = null;
        this.resizeObserver = null;
        this.isDragging = false;

        // Bind methods
        this.handleResize = this.handleResize.bind(this);
        this.handleMouseMove = this.handleMouseMove.bind(this);
        this.handleMouseLeave = this.handleMouseLeave.bind(this);
    }

    /**
     * Get global time range from dashboard controls
     */
    getGlobalTimeRange() {
        if (!window.dashboardControls || !window.dashboardControls.currentTimeRange) {
            return 86400; // 1 day in seconds
        }
        return window.dashboardControls.parseTimeRangeToSeconds(window.dashboardControls.currentTimeRange);
    }

    /**
     * Initialize the timeline component
     */
    async initialize() {
        this.container = document.getElementById(this.containerId);
        if (!this.container) {
            console.error(`Container not found: ${this.containerId}`);
            return false;
        }

        // Create DOM structure
        this.createDOMStructure();

        // Fetch and render data
        await this.fetchData();
        this.render();

        // Setup event listeners
        this.setupEventListeners();

        console.log(`StateTimeline initialized: ${this.options.metricName}`);
        return true;
    }

    /**
     * Create DOM structure for timeline
     */
    createDOMStructure() {
        this.container.innerHTML = `
            <div class="timeline-wrapper">
                <div class="timeline-header">
                    <h3 class="timeline-title">${this.options.title}</h3>
                </div>
                <div class="timeline-canvas-container">
                    <canvas id="${this.containerId}-canvas"></canvas>
                </div>
                <div class="timeline-legend">
                    ${Object.entries(this.options.stateLabels).map(([value, label]) => `
                        <span class="legend-item">
                            <span class="legend-color" style="background-color: ${this.options.colors[value]}"></span>
                            <span class="legend-label">${label}</span>
                        </span>
                    `).join('')}
                </div>
                <div class="timeline-tooltip" id="${this.containerId}-tooltip" style="display: none;"></div>
            </div>
        `;

        this.canvas = document.getElementById(`${this.containerId}-canvas`);
        this.ctx = this.canvas.getContext('2d');
        this.tooltip = document.getElementById(`${this.containerId}-tooltip`);
    }

    /**
     * Fetch timeline data from API
     */
    async fetchData(customTimeRange = null) {
        try {
            let url;
            if (customTimeRange && customTimeRange.start && customTimeRange.end) {
                // Use specific time range from chart zoom
                const start = Math.floor(customTimeRange.start);
                const end = Math.floor(customTimeRange.end);
                const seconds = end - start;
                url = `/api/timeseries/${this.options.metricName}?seconds=${seconds}&aggregation=max`;
                // Store the custom time range
                this.customTimeRange = { start, end };
            } else {
                // Use global dashboard time range
                const seconds = this.getGlobalTimeRange();
                url = `/api/timeseries/${this.options.metricName}?seconds=${seconds}&aggregation=max`;
                this.customTimeRange = null;
            }

            const response = await fetch(url);

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const result = await response.json();
            this.data = result.data || {};
            this.clients = result.clients || {};
            this.timeRange = result.time_range || {};

            // If we have custom time range, override the returned time range
            if (this.customTimeRange) {
                this.timeRange.start = this.customTimeRange.start;
                this.timeRange.end = this.customTimeRange.end;
            }

            console.log(`Fetched timeline data for ${Object.keys(this.data).length} clients`);
        } catch (error) {
            console.error('Error fetching timeline data:', error);
            this.data = {};
            this.clients = {};
        }
    }

    /**
     * Process data into state transitions
     * Converts raw timeseries data into state change events
     */
    processData() {
        const processed = {};
        const rangeStart = this.timeRange.start || 0;
        const rangeEnd = this.timeRange.end || Math.floor(Date.now() / 1000);

        for (const [clientId, points] of Object.entries(this.data)) {
            if (!points || points.length === 0) continue;

            const states = [];
            let currentState = null;
            let stateStart = null;

            // Sort by timestamp
            const sortedPoints = [...points].sort((a, b) => a.timestamp - b.timestamp);

            for (let i = 0; i < sortedPoints.length; i++) {
                const point = sortedPoints[i];
                const state = point.value > 0 ? 1 : 0;

                if (state !== currentState) {
                    // State changed
                    if (currentState !== null && stateStart !== null) {
                        // Save previous state
                        states.push({
                            state: currentState,
                            start: stateStart,
                            end: point.timestamp
                        });
                    }

                    currentState = state;
                    stateStart = point.timestamp;
                }
            }

            // Add final state extending to end of time range
            if (currentState !== null && stateStart !== null) {
                states.push({
                    state: currentState,
                    start: stateStart,
                    end: rangeEnd
                });
            }

            processed[clientId] = states;
        }

        return processed;
    }

    /**
     * Render the timeline canvas
     */
    render() {
        if (!this.canvas || !this.ctx) return;

        // Get container dimensions
        const containerWidth = this.container.offsetWidth;
        const clientIds = Object.keys(this.data).filter(id => this.data[id] && this.data[id].length > 0);
        const numClients = clientIds.length;

        // Calculate canvas height based on number of clients
        const canvasHeight = Math.max(
            this.options.height,
            numClients * (this.options.laneHeight + this.options.laneGap) + 40
        );

        // Set canvas size (account for device pixel ratio for crisp rendering)
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = containerWidth * dpr;
        this.canvas.height = canvasHeight * dpr;
        this.canvas.style.width = `${containerWidth}px`;
        this.canvas.style.height = `${canvasHeight}px`;
        this.ctx.scale(dpr, dpr);

        // Clear canvas
        this.ctx.clearRect(0, 0, containerWidth, canvasHeight);

        if (numClients === 0) {
            this.renderEmptyState(containerWidth, canvasHeight);
            return;
        }

        // Process data into state transitions
        const processedData = this.processData();

        // Get time range
        const startTime = this.timeRange.start || Math.min(...Object.values(this.data)
            .flat()
            .map(p => p.timestamp));
        const endTime = this.timeRange.end || Math.floor(Date.now() / 1000);
        const timeSpan = endTime - startTime;

        // Store for tooltip calculations
        this.renderData = {
            processedData,
            clientIds,
            startTime,
            endTime,
            timeSpan,
            containerWidth,
            canvasHeight
        };

        // Draw lanes
        clientIds.forEach((clientId, index) => {
            const y = index * (this.options.laneHeight + this.options.laneGap) + 20;
            this.drawLane(clientId, processedData[clientId] || [], y, startTime, endTime, timeSpan, containerWidth);
        });
    }

    /**
     * Draw a single client lane
     */
    drawLane(clientId, states, y, startTime, endTime, timeSpan, width) {
        const clientName = this.clients[clientId] || `Client ${clientId}`;

        // Draw client label (left side)
        this.ctx.fillStyle = '#666';
        this.ctx.font = '12px monospace';
        this.ctx.textAlign = 'left';
        this.ctx.textBaseline = 'middle';
        this.ctx.fillText(clientName, 5, y + this.options.laneHeight / 2);

        // Draw states
        const labelWidth = 100; // Reserve space for client labels
        const timelineWidth = width - labelWidth - 10;

        // If no states, fill entire lane with "no data" gray background
        if (states.length === 0) {
            this.ctx.fillStyle = '#f0f0f0'; // Light gray for no data
            this.ctx.fillRect(labelWidth, y, timelineWidth, this.options.laneHeight);

            // Add "No data" text
            this.ctx.fillStyle = '#999';
            this.ctx.font = '11px sans-serif';
            this.ctx.textAlign = 'center';
            this.ctx.fillText('No data', labelWidth + timelineWidth / 2, y + this.options.laneHeight / 2);
        } else {
            // Fill background with light gray first (for any gaps)
            this.ctx.fillStyle = '#f8f8f8';
            this.ctx.fillRect(labelWidth, y, timelineWidth, this.options.laneHeight);

            // Fill gap before first state if exists (draw BEFORE states so states are on top)
            if (states.length > 0 && states[0].start > startTime) {
                const gapWidth = (states[0].start - startTime) / timeSpan * timelineWidth;
                if (gapWidth > 0) {
                    this.ctx.fillStyle = '#e0e0e0'; // Darker gray for data gap
                    this.ctx.fillRect(labelWidth, y, gapWidth, this.options.laneHeight);
                }
            }

            // Draw state rectangles on top
            states.forEach(stateData => {
                const x1 = labelWidth + (stateData.start - startTime) / timeSpan * timelineWidth;
                const x2 = labelWidth + (stateData.end - startTime) / timeSpan * timelineWidth;
                const rectWidth = Math.max(2, x2 - x1); // Minimum 2px width

                // Draw state rectangle
                this.ctx.fillStyle = this.options.colors[stateData.state] || '#ccc';
                this.ctx.fillRect(x1, y, rectWidth, this.options.laneHeight);
            });
        }

        // Draw lane border
        this.ctx.strokeStyle = '#ddd';
        this.ctx.lineWidth = 1;
        this.ctx.strokeRect(labelWidth, y, timelineWidth, this.options.laneHeight);
    }

    /**
     * Render empty state message
     */
    renderEmptyState(width, height) {
        this.ctx.fillStyle = '#999';
        this.ctx.font = '14px sans-serif';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        this.ctx.fillText('No data available', width / 2, height / 2);
    }

    /**
     * Setup event listeners
     */
    setupEventListeners() {
        // Mouse events for tooltips
        this.canvas.addEventListener('mousemove', this.handleMouseMove);
        this.canvas.addEventListener('mouseleave', this.handleMouseLeave);

        // Resize observer for responsive rendering
        this.resizeObserver = new ResizeObserver(() => {
            this.handleResize();
        });
        this.resizeObserver.observe(this.container);

        // Listen for dashboard time range changes (from dropdown)
        document.addEventListener('timeRangeChanged', async () => {
            await this.refresh();
        });

        // Listen for chart zoom/pan changes (from uPlot interaction)
        document.addEventListener('chartZoomChanged', async (event) => {
            const { start, end } = event.detail;
            await this.refreshWithTimeRange(start, end);
        });
    }

    /**
     * Handle canvas resize
     */
    handleResize() {
        // Debounce resize to avoid excessive redraws
        clearTimeout(this.resizeTimeout);
        this.resizeTimeout = setTimeout(() => {
            this.render();
        }, 100);
    }

    /**
     * Handle mouse move for tooltips
     */
    handleMouseMove(event) {
        if (!this.renderData) return;

        const rect = this.canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;

        const { processedData, clientIds, startTime, timeSpan, containerWidth } = this.renderData;
        const labelWidth = 100;
        const timelineWidth = containerWidth - labelWidth - 10;

        // Find which lane we're hovering over
        const laneIndex = Math.floor((y - 20) / (this.options.laneHeight + this.options.laneGap));

        if (laneIndex < 0 || laneIndex >= clientIds.length) {
            this.hideTooltip();
            return;
        }

        const clientId = clientIds[laneIndex];
        const states = processedData[clientId] || [];

        // Calculate timestamp from x position
        const relativeX = x - labelWidth;
        if (relativeX < 0 || relativeX > timelineWidth) {
            this.hideTooltip();
            return;
        }

        const timestamp = startTime + (relativeX / timelineWidth) * timeSpan;

        // Find which state we're hovering over
        const state = states.find(s => timestamp >= s.start && timestamp <= s.end);

        if (state) {
            this.showTooltip(event, clientId, state);
        } else {
            this.hideTooltip();
        }
    }

    /**
     * Show tooltip
     */
    showTooltip(event, clientId, state) {
        const clientName = this.clients[clientId] || `Client ${clientId}`;
        const stateLabel = this.options.stateLabels[state.state] || `State ${state.state}`;
        const startTime = new Date(state.start * 1000).toLocaleString();
        const endTime = new Date(state.end * 1000).toLocaleString();
        const duration = this.formatDuration(state.end - state.start);

        this.tooltip.innerHTML = `
            <div class="tooltip-content">
                <div><strong>${clientName}</strong></div>
                <div>Status: <span style="color: ${this.options.colors[state.state]}">${stateLabel}</span></div>
                <div>From: ${startTime}</div>
                <div>To: ${endTime}</div>
                <div>Duration: ${duration}</div>
            </div>
        `;

        this.tooltip.style.display = 'block';
        this.tooltip.style.left = `${event.pageX + 10}px`;
        this.tooltip.style.top = `${event.pageY + 10}px`;
    }

    /**
     * Hide tooltip
     */
    hideTooltip() {
        if (this.tooltip) {
            this.tooltip.style.display = 'none';
        }
    }

    /**
     * Handle mouse leave
     */
    handleMouseLeave() {
        this.hideTooltip();
    }

    /**
     * Format duration in human-readable form
     */
    formatDuration(seconds) {
        if (seconds < 60) return `${Math.floor(seconds)}s`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
        return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
    }

    /**
     * Refresh timeline data
     */
    async refresh() {
        await this.fetchData();
        this.render();
    }

    /**
     * Refresh timeline with specific time range (from chart zoom)
     */
    async refreshWithTimeRange(start, end) {
        await this.fetchData({ start, end });
        this.render();
    }

    /**
     * Destroy the timeline
     */
    destroy() {
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
        }

        if (this.canvas) {
            this.canvas.removeEventListener('mousemove', this.handleMouseMove);
            this.canvas.removeEventListener('mouseleave', this.handleMouseLeave);
        }

        if (this.container) {
            this.container.innerHTML = '';
        }
    }
}

// Export for global usage
window.StateTimeline = StateTimeline;

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = StateTimeline;
}
