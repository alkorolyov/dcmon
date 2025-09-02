/**
 * dcmon Dashboard JavaScript
 * 
 * Minimal JavaScript for dashboard functionality.
 * Most logic is handled server-side in Python for AI maintainability.
 */

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('dcmon Dashboard initialized');
    initializeAutoRefresh();
});

/**
 * Initialize auto-refresh functionality
 */
function initializeAutoRefresh() {
    // Auto-refresh is handled by htmx attributes in HTML
    // This function can be extended for additional refresh logic
    console.log('Auto-refresh initialized');
}

/**
 * Update last refresh timestamp
 */
function updateLastRefreshTime() {
    const now = new Date();
    const timeString = now.toLocaleTimeString();
    const element = document.getElementById('last-update');
    if (element) {
        element.textContent = timeString;
    }
}

/**
 * Handle client card interactions
 */
function viewClientDetails(clientId) {
    // TODO: Implement client details view
    console.log('View details for client:', clientId);
    // For now, just log - will be implemented in future updates
    alert(`Client details for ID ${clientId} - Feature coming soon!`);
}

/**
 * Handle fan control interface
 */
function showFanControl(clientId) {
    // TODO: Implement fan control interface
    console.log('Show fan control for client:', clientId);
    // For now, just log - will be implemented in future updates
    alert(`Fan control for client ID ${clientId} - Feature coming soon!`);
}


/**
 * Utility function to format numbers
 */
function formatNumber(num, decimals = 1) {
    if (num === null || num === undefined) return 'N/A';
    return Number(num).toFixed(decimals);
}

/**
 * Utility function to format bytes
 */
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// Global error handler for any JavaScript errors
window.addEventListener('error', function(event) {
    console.error('Dashboard JavaScript Error:', event.error);
});

// Global handler for htmx events (if needed)
document.addEventListener('htmx:responseError', function(event) {
    console.error('htmx Response Error:', event.detail);
});

document.addEventListener('htmx:afterRequest', function(event) {
    // Update timestamp after successful htmx requests
    if (event.detail.successful) {
        updateLastRefreshTime();
    }
});