/**
 * Dashboard Controls Component
 * 
 * Handles refresh rate, time range, and other dashboard control dropdowns
 */

class DashboardControls {
    constructor() {
        this.refreshInterval = null;
        this.currentRefreshRate = 30; // seconds
        this.currentTimeRange = '1d'; // Default to 1 day
        this.activeDropdown = null;
        
        this.initialize();
        console.log('DashboardControls initialized');
    }
    
    /**
     * Initialize all dashboard controls
     */
    initialize() {
        this.initializeRefreshControls();
        this.initializeTimeRangeControls();
        this.initializeGlobalEventListeners();
        this.startAutoRefresh();
    }
    
    /**
     * Initialize refresh rate dropdown controls
     */
    initializeRefreshControls() {
        const refreshButton = document.getElementById('refresh-interval-btn');
        const refreshDropdown = document.getElementById('refresh-dropdown');
        const refreshItems = refreshDropdown?.querySelectorAll('.dropdown-item') || [];
        
        if (!refreshButton || !refreshDropdown) return;
        
        // Setup dropdown toggle
        this.setupDropdownToggle(refreshButton, refreshDropdown, 'refresh');
        
        // Handle refresh rate selection
        refreshItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                const value = item.getAttribute('data-value');
                
                if (value === 'custom') {
                    this.handleCustomRefresh();
                } else if (value === 'pause') {
                    this.pauseAutoRefresh();
                } else {
                    this.updateRefreshRate(parseInt(value));
                }
                
                // Update active state
                refreshItems.forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                
                // Close dropdown
                this.closeDropdown(refreshDropdown, refreshButton);
            });
        });
        
        // Manual refresh button
        const manualRefreshBtn = document.getElementById('manual-refresh-btn');
        if (manualRefreshBtn) {
            manualRefreshBtn.addEventListener('click', () => {
                this.triggerManualRefresh();
            });
        }
    }
    
    /**
     * Initialize time range dropdown controls
     */
    initializeTimeRangeControls() {
        const timerangeButton = document.getElementById('timerange-btn');
        const timerangeDropdown = document.getElementById('timerange-dropdown');
        const timerangeItems = timerangeDropdown?.querySelectorAll('.dropdown-item') || [];
        
        if (!timerangeButton || !timerangeDropdown) return;
        
        // Setup dropdown toggle
        this.setupDropdownToggle(timerangeButton, timerangeDropdown, 'timerange');
        
        // Handle time range selection
        timerangeItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                const value = item.getAttribute('data-value');
                
                if (value === 'custom') {
                    this.handleCustomTimeRange();
                } else {
                    this.updateTimeRange(value);
                }
                
                // Update active state
                timerangeItems.forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                
                // Close dropdown
                this.closeDropdown(timerangeDropdown, timerangeButton);
            });
        });
    }
    
    /**
     * Setup dropdown toggle functionality
     */
    setupDropdownToggle(button, dropdown, type) {
        button.addEventListener('click', (e) => {
            e.stopPropagation();
            
            // Close other dropdowns
            this.closeAllDropdowns();
            
            // Toggle current dropdown
            const isOpen = dropdown.classList.contains('show');
            if (isOpen) {
                this.closeDropdown(dropdown, button);
            } else {
                this.openDropdown(dropdown, button, type);
            }
        });
    }
    
    /**
     * Open a dropdown
     */
    openDropdown(dropdown, button, type) {
        dropdown.classList.add('show');
        button.classList.add('active');
        this.activeDropdown = { dropdown, button, type };
    }
    
    /**
     * Close a dropdown
     */
    closeDropdown(dropdown, button) {
        dropdown.classList.remove('show');
        button.classList.remove('active');
        if (this.activeDropdown?.dropdown === dropdown) {
            this.activeDropdown = null;
        }
    }
    
    /**
     * Close all open dropdowns
     */
    closeAllDropdowns() {
        document.querySelectorAll('.dropdown-menu.show').forEach(dropdown => {
            dropdown.classList.remove('show');
        });
        document.querySelectorAll('.dropdown-toggle.active').forEach(button => {
            button.classList.remove('active');
        });
        this.activeDropdown = null;
    }
    
    /**
     * Initialize global event listeners
     */
    initializeGlobalEventListeners() {
        // Close dropdowns when clicking outside
        document.addEventListener('click', (e) => {
            if (this.activeDropdown && !e.target.closest('.dropdown')) {
                this.closeAllDropdowns();
            }
        });
        
        // Handle escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.activeDropdown) {
                this.closeAllDropdowns();
            }
        });
    }
    
    /**
     * Update refresh rate
     */
    updateRefreshRate(seconds) {
        this.currentRefreshRate = seconds;
        
        // Update button text
        const refreshButton = document.getElementById('refresh-interval-btn');
        const refreshText = refreshButton?.querySelector('.dropdown-text');
        if (refreshText) {
            refreshText.textContent = this.formatRefreshRate(seconds);
        }
        
        // Restart auto-refresh with new interval
        this.stopAutoRefresh();
        this.startAutoRefresh();
        
        console.log(`Refresh rate updated to ${seconds}s`);
    }
    
    /**
     * Update time range
     */
    updateTimeRange(range) {
        this.currentTimeRange = range;
        
        // Update button text
        const timerangeButton = document.getElementById('timerange-btn');
        const timerangeText = timerangeButton?.querySelector('.dropdown-text');
        if (timerangeText) {
            timerangeText.textContent = this.formatTimeRange(range);
        }
        
        // Refresh charts with new time range
        this.refreshChartsWithTimeRange(range);
        
        console.log(`Time range updated to ${range}`);
    }
    
    /**
     * Handle custom refresh rate input
     */
    handleCustomRefresh() {
        const customSeconds = prompt('Enter refresh interval in seconds (5-300):', this.currentRefreshRate);
        if (customSeconds && !isNaN(customSeconds)) {
            const seconds = Math.max(5, Math.min(300, parseInt(customSeconds)));
            this.updateRefreshRate(seconds);
        }
    }
    
    /**
     * Handle custom time range input
     */
    handleCustomTimeRange() {
        const customRange = prompt('Enter time range (e.g., "2h", "30m", "7d"):', this.currentTimeRange);
        if (customRange && this.isValidTimeRange(customRange)) {
            this.updateTimeRange(customRange);
        }
    }
    
    /**
     * Pause auto-refresh
     */
    pauseAutoRefresh() {
        this.stopAutoRefresh();
        
        const refreshButton = document.getElementById('refresh-interval-btn');
        const refreshText = refreshButton?.querySelector('.dropdown-text');
        if (refreshText) {
            refreshText.textContent = 'Paused';
        }
        
        console.log('Auto-refresh paused');
    }
    
    /**
     * Start auto-refresh
     */
    startAutoRefresh() {
        if (this.refreshInterval || this.currentRefreshRate <= 0) return;
        
        this.refreshInterval = setInterval(() => {
            this.triggerAutoRefresh();
        }, this.currentRefreshRate * 1000);
        
        console.log(`Auto-refresh started: ${this.currentRefreshRate}s interval`);
    }
    
    /**
     * Stop auto-refresh
     */
    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
            console.log('Auto-refresh stopped');
        }
    }
    
    /**
     * Trigger manual refresh
     */
    triggerManualRefresh() {
        // Manual refresh should clear cache and get fresh data
        if (window.chartManager) {
            window.chartManager.forceRefreshAll();
        }
        
        // Refresh tables
        if (window.clientsTable) {
            window.clientsTable.refreshTable();
        }
        
        // Show feedback
        const manualRefreshBtn = document.getElementById('manual-refresh-btn');
        if (manualRefreshBtn) {
            const originalText = manualRefreshBtn.textContent;
            manualRefreshBtn.textContent = 'Refreshing...';
            manualRefreshBtn.disabled = true;
            
            setTimeout(() => {
                manualRefreshBtn.textContent = originalText;
                manualRefreshBtn.disabled = false;
            }, 1000);
        }
        
        console.log('Manual refresh triggered (force refresh with cache clear)');
    }
    
    /**
     * Trigger auto-refresh
     */
    triggerAutoRefresh() {
        this.refreshDashboard();
        
        // Update last refresh time
        const now = new Date();
        const refreshTime = document.querySelector('.refresh-time');
        if (refreshTime) {
            refreshTime.textContent = now.toLocaleTimeString();
        }
    }
    
    /**
     * Refresh dashboard components
     */
    refreshDashboard() {
        // Refresh clients table
        if (window.clientsTable) {
            window.clientsTable.refreshTable();
        }

        // Refresh charts with auto-refresh optimization
        if (window.chartManager) {
            window.chartManager.refreshAll(true); // true = isAutoRefresh
        }

        // Refresh VastAI timeline
        if (window.vastaiTimeline) {
            window.vastaiTimeline.refresh();
        }

        // Trigger HTMX refresh for tables
        const refreshElements = document.querySelectorAll('[hx-get*="refresh"]');
        refreshElements.forEach(element => {
            if (typeof htmx !== 'undefined') {
                htmx.trigger(element, 'refresh');
            }
        });
    }
    
    /**
     * Refresh charts with new time range
     */
    refreshChartsWithTimeRange(range) {
        // Convert range to seconds for API
        const seconds = this.parseTimeRangeToSeconds(range);

        // Update time range with smart caching
        window.chartManager.updateTimeRange(seconds);

        // Dispatch custom event for other components (e.g., timeline)
        document.dispatchEvent(new CustomEvent('timeRangeChanged', {
            detail: { range, seconds }
        }));
    }
    
    /**
     * Utility functions
     */
    formatRefreshRate(seconds) {
        if (seconds < 60) return `${seconds}s`;
        return `${Math.round(seconds / 60)}m`;
    }
    
    formatTimeRange(range) {
        const rangeMap = {
            '5m': 'Last 5 minutes',
            '15m': 'Last 15 minutes',
            '30m': 'Last 30 minutes',
            '1h': 'Last hour',
            '3h': 'Last 3 hours',
            '6h': 'Last 6 hours',
            '12h': 'Last 12 hours',
            '1d': 'Last day',
            '2d': 'Last 2 days',
            '7d': 'Last week',
            '30d': 'Last month',
            '90d': 'Last 3 months'
        };
        return rangeMap[range] || range;
    }
    
    parseTimeRangeToSeconds(range) {
        const match = range.match(/^(\d+)([hmd])$/);
        if (!match) return 86400; // Default to 24 hours = 86400 seconds
        
        const [, value, unit] = match;
        const num = parseInt(value);
        
        switch (unit) {
            case 'm': return num * 60;      // minutes to seconds
            case 'h': return num * 3600;    // hours to seconds  
            case 'd': return num * 86400;   // days to seconds
            default: return 86400;
        }
    }
    
    isValidTimeRange(range) {
        return /^\d+[hmd]$/.test(range);
    }
}

// Initialize dashboard controls when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    window.dashboardControls = new DashboardControls();
});

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DashboardControls;
}