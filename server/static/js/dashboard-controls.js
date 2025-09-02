/**
 * Dashboard Controls - Grafana-style dropdown handlers
 */

document.addEventListener('DOMContentLoaded', function() {
    initializeDashboardControls();
});

function initializeDashboardControls() {
    // Initialize refresh rate dropdown
    const refreshButton = document.getElementById('refresh-interval-btn');
    const refreshDropdown = document.getElementById('refresh-dropdown');
    const refreshItems = refreshDropdown?.querySelectorAll('.dropdown-item') || [];
    
    // Initialize time range dropdown
    const timerangeButton = document.getElementById('timerange-btn');
    const timerangeDropdown = document.getElementById('timerange-dropdown');
    const timerangeItems = timerangeDropdown?.querySelectorAll('.dropdown-item') || [];
    
    // Dropdown toggle handlers
    setupDropdownToggle(refreshButton, refreshDropdown);
    setupDropdownToggle(timerangeButton, timerangeDropdown);
    
    // Refresh rate selection
    refreshItems.forEach(item => {
        item.addEventListener('click', function(e) {
            e.stopPropagation();
            const value = this.getAttribute('data-value');
            
            if (value === 'custom') {
                handleCustomRefresh();
            } else {
                updateRefreshRate(value);
            }
            
            // Update active state
            refreshItems.forEach(i => i.classList.remove('active'));
            this.classList.add('active');
            
            // Close dropdown
            refreshDropdown?.classList.remove('show');
            refreshButton?.classList.remove('active');
        });
    });
    
    // Time range selection
    timerangeItems.forEach(item => {
        item.addEventListener('click', function(e) {
            e.stopPropagation();
            const value = this.getAttribute('data-value');
            
            if (value === 'absolute') {
                handleAbsoluteTimeRange();
            } else {
                updateTimeRange(value);
            }
            
            // Update active state
            timerangeItems.forEach(i => i.classList.remove('active'));
            this.classList.add('active');
            
            // Close dropdown
            timerangeDropdown?.classList.remove('show');
            timerangeButton?.classList.remove('active');
        });
    });
    
    // Close dropdowns when clicking outside
    document.addEventListener('click', function(e) {
        if (!refreshButton.contains(e.target)) {
            refreshDropdown.classList.remove('show');
            refreshButton.classList.remove('active');
        }
        if (!timerangeButton.contains(e.target)) {
            timerangeDropdown.classList.remove('show');
            timerangeButton.classList.remove('active');
        }
    });
}

function setupDropdownToggle(button, dropdown) {
    button.addEventListener('click', function(e) {
        e.stopPropagation();
        
        // Close other dropdown if open
        const otherDropdowns = document.querySelectorAll('.dropdown-menu');
        const otherButtons = document.querySelectorAll('.control-button');
        
        otherDropdowns.forEach(d => {
            if (d !== dropdown) {
                d.classList.remove('show');
            }
        });
        
        otherButtons.forEach(b => {
            if (b !== button) {
                b.classList.remove('active');
            }
        });
        
        // Toggle current dropdown
        dropdown?.classList.toggle('show');
        button?.classList.toggle('active');
    });
}

function updateRefreshRate(seconds) {
    const refreshText = document.querySelector('#refresh-interval-btn span');
    let displayText;
    
    switch(seconds) {
        case '15':
            displayText = '15s';
            break;
        case '30':
            displayText = '30s';
            break;
        case '60':
            displayText = '1m';
            break;
        case '300':
            displayText = '5m';
            break;
        default:
            displayText = `${seconds}s`;
    }
    
    refreshText.textContent = displayText;
    
    // Update HTMX trigger interval
    const clientsTable = document.getElementById('clients-table');
    if (clientsTable) {
        const currentUrl = clientsTable.getAttribute('hx-get');
        clientsTable.setAttribute('hx-trigger', `every ${seconds}s`);
        
        // Trigger immediate refresh to restart with new interval
        if (window.htmx) {
            htmx.trigger(clientsTable, 'refresh');
        }
    }
    
    console.log(`Refresh rate updated to ${seconds} seconds`);
}

function updateTimeRange(range) {
    const timerangeText = document.querySelector('#timerange-btn span');
    let displayText;
    
    switch(range) {
        case '5m':
            displayText = 'Last 5m';
            break;
        case '15m':
            displayText = 'Last 15m';
            break;
        case '30m':
            displayText = 'Last 30m';
            break;
        case '1h':
            displayText = 'Last 1h';
            break;
        case '3h':
            displayText = 'Last 3h';
            break;
        case '6h':
            displayText = 'Last 6h';
            break;
        case '12h':
            displayText = 'Last 12h';
            break;
        case '24h':
            displayText = 'Last 24h';
            break;
        case '2d':
            displayText = 'Last 2d';
            break;
        case '7d':
            displayText = 'Last 7d';
            break;
        case '30d':
            displayText = 'Last 30d';
            break;
        case '90d':
            displayText = 'Last 90d';
            break;
        default:
            displayText = `${range}`;
    }
    
    timerangeText.textContent = displayText;
    
    // TODO: Implement actual time range filtering in backend
    console.log(`Time range updated to ${range}`);
}

function handleCustomRefresh() {
    const customValue = prompt('Enter custom refresh interval (seconds):', '120');
    if (customValue && !isNaN(customValue) && parseInt(customValue) > 0) {
        updateRefreshRate(customValue);
        
        // Update the custom option text to show the selected value
        const customOption = document.querySelector('[data-value="custom"]');
        customOption.textContent = `Custom (${customValue}s)`;
        customOption.setAttribute('data-value', customValue);
    }
}

function handleAbsoluteTimeRange() {
    // TODO: Implement absolute time range picker
    alert('Absolute time range picker - Coming soon!');
    console.log('Absolute time range selection requested');
}