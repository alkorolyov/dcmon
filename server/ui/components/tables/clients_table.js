/**
 * Clients Table Component - JavaScript functionality
 * 
 * Handles auto-refresh and real-time updates for the clients health table
 */

class ClientsTable {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.refreshInterval = options.refreshInterval || 30000; // 30 seconds
        this.autoRefresh = options.autoRefresh !== false; // Default: enabled
        this.refreshTimer = null;
        
        this.initializeEventListeners();
        this.startAutoRefresh();
        
        console.log('ClientsTable initialized');
    }
    
    /**
     * Initialize event listeners for the table
     */
    initializeEventListeners() {
        // Handle HTMX after-request events
        document.addEventListener('htmx:afterRequest', (event) => {
            if (event.detail.successful && this.isTableRefresh(event)) {
                this.onTableUpdated();
            }
        });
        
        // Handle HTMX before-request events
        document.addEventListener('htmx:beforeRequest', (event) => {
            if (this.isTableRefresh(event)) {
                this.onTableRefreshing();
            }
        });
        
        // Handle HTMX errors
        document.addEventListener('htmx:responseError', (event) => {
            if (this.isTableRefresh(event)) {
                this.onTableError(event.detail);
            }
        });
    }
    
    /**
     * Check if an HTMX event is related to table refresh
     */
    isTableRefresh(event) {
        const target = event.target || event.detail?.target;
        return target && (
            target.closest('#' + this.containerId) ||
            target.id === this.containerId ||
            event.detail?.pathInfo?.requestPath?.includes('refresh/clients')
        );
    }
    
    /**
     * Called when table is being refreshed
     */
    onTableRefreshing() {
        // Add loading indicator or update UI
        const tables = this.container?.querySelectorAll('.metric-table');
        tables?.forEach(table => {
            table.classList.add('table-loading');
        });
    }
    
    /**
     * Called when table has been successfully updated
     */
    onTableUpdated() {
        // Update timestamps and remove loading indicators
        const now = new Date();
        const timeString = now.toLocaleTimeString();
        
        // Update any timestamp elements
        document.querySelectorAll('.timestamp').forEach(el => {
            el.textContent = timeString;
        });
        
        // Remove loading state
        const tables = this.container?.querySelectorAll('.metric-table');
        tables?.forEach(table => {
            table.classList.remove('table-loading');
        });
        
        // Update last refresh time in header if it exists
        const refreshTime = document.querySelector('.refresh-time');
        if (refreshTime) {
            refreshTime.textContent = timeString;
        }
        
        console.log('Clients table updated at', timeString);
    }
    
    /**
     * Called when table refresh encounters an error
     */
    onTableError(errorDetail) {
        console.error('Clients table refresh error:', errorDetail);
        
        // Remove loading state
        const tables = this.container?.querySelectorAll('.metric-table');
        tables?.forEach(table => {
            table.classList.remove('table-loading');
        });
        
        // Show error indicator (you could add a toast notification here)
        const errorTime = new Date().toLocaleTimeString();
        console.warn(`Table refresh failed at ${errorTime}`);
    }
    
    /**
     * Start auto-refresh timer
     */
    startAutoRefresh() {
        if (!this.autoRefresh || this.refreshTimer) return;
        
        this.refreshTimer = setInterval(() => {
            this.refreshTable();
        }, this.refreshInterval);
        
        console.log(`Auto-refresh started: ${this.refreshInterval}ms interval`);
    }
    
    /**
     * Stop auto-refresh timer
     */
    stopAutoRefresh() {
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = null;
            console.log('Auto-refresh stopped');
        }
    }
    
    /**
     * Manually refresh the table
     */
    refreshTable() {
        // HTMX attribute is on the container itself, not a child element
        const refreshElement = this.container.hasAttribute('hx-get') ? this.container : null;
        
        if (!refreshElement) {
            throw new Error(`HTMX refresh element not found in container: ${this.container.id}`);
        }
        
        if (typeof htmx === 'undefined') {
            throw new Error('HTMX library not loaded');
        }
        
        htmx.trigger(refreshElement, 'refresh');
    }
    
    /**
     * Update refresh interval
     */
    setRefreshInterval(intervalMs) {
        this.refreshInterval = intervalMs;
        
        if (this.refreshTimer) {
            this.stopAutoRefresh();
            this.startAutoRefresh();
        }
    }
    
    /**
     * Get current table statistics
     */
    getTableStats() {
        if (!this.container) return null;
        
        const rows = this.container.querySelectorAll('.client-row');
        const onlineRows = this.container.querySelectorAll('.client-row.online');
        const offlineRows = this.container.querySelectorAll('.client-row.offline');
        
        return {
            total: rows.length,
            online: onlineRows.length,
            offline: offlineRows.length,
            lastRefresh: this.lastRefresh || null
        };
    }
    
    /**
     * Highlight specific client row
     */
    highlightClient(hostname) {
        // Remove existing highlights
        this.container?.querySelectorAll('.client-row.highlighted')
            .forEach(row => row.classList.remove('highlighted'));
        
        // Add highlight to specific client
        const targetRow = this.container?.querySelector(
            `.client-row .hostname-cell:contains("${hostname}")`
        )?.closest('.client-row');
        
        if (targetRow) {
            targetRow.classList.add('highlighted');
            targetRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }
    
    /**
     * Destroy the table component
     */
    destroy() {
        this.stopAutoRefresh();
        
        // Remove event listeners if needed
        // (In practice, document event listeners don't need removal for this use case)
        
        console.log('ClientsTable destroyed');
    }
}

// Export for global usage
window.ClientsTable = ClientsTable;

// Export for module usage  
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ClientsTable;
}