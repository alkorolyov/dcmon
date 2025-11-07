/**
 * Client Detail Modal Component
 * Handles opening, closing, and interaction with client detail modals
 */

class ClientDetailModal {
    constructor() {
        this.currentModal = null;
        this.expandedSections = new Set();
        this.init();
    }

    init() {
        // Set up global functions for HTML onclick handlers
        window.closeClientModal = () => this.close();
        window.toggleLogSource = (clientId, logSource) => this.toggleLogSource(clientId, logSource);
        window.filterLogsBySeverity = (severity) => this.filterLogsBySeverity(severity);
        window.switchTab = (tabId) => this.switchTab(tabId);
        window.setFanMode = (mode, clientId) => this.setFanMode(mode, clientId);
        window.getFanStatus = (clientId) => this.getFanStatus(clientId);
        window.setFanSpeeds = (speed, clientId) => this.setFanSpeeds(speed, clientId);
        window.setCustomFanSpeed = (clientId) => this.setCustomFanSpeed(clientId);
        window.getSystemInfo = (type, clientId) => this.getSystemInfo(type, clientId);
        window.executeCustomIPMI = (clientId) => this.executeCustomIPMI(clientId);
        
        // Close modal on overlay click (only if clicking directly on overlay, not content)
        document.addEventListener('click', (event) => {
            // Only close if we clicked directly on the overlay, not a child element
            if (event.target.id === 'client-detail-modal' &&
                event.target.classList.contains('modal-overlay')) {
                console.log('DEBUG: Closing modal - click detected on overlay', event.target);
                this.close();
            }
        });

        // Close modal on escape key
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && this.currentModal) {
                this.close();
            }
        });

        console.log('ClientDetailModal initialized');
    }

    async open(clientId) {
        try {
            console.log(`Opening client detail modal for client ${clientId}`);
            
            // Close any existing modal
            this.close();

            // Show loading state
            this.showLoading();

            // Fetch modal content
            const response = await fetch(`/dashboard/client/${clientId}/modal`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const modalHtml = await response.text();
            
            // Remove loading and add modal to page
            this.removeLoading();
            document.body.insertAdjacentHTML('beforeend', modalHtml);
            
            // Store reference to current modal
            this.currentModal = document.getElementById('client-detail-modal');
            
            // Prevent body scroll
            document.body.style.overflow = 'hidden';
            
            // Initialize HTMX for any new content
            if (window.htmx) {
                htmx.process(this.currentModal);
            }

            console.log('Client detail modal opened successfully');

        } catch (error) {
            console.error('Error opening client detail modal:', error);
            this.removeLoading();
            this.showError(`Failed to load client details: ${error.message}`);
        }
    }

    close() {
        if (this.currentModal) {
            console.log('Closing client detail modal');
            
            // Restore body scroll
            document.body.style.overflow = '';
            
            // Remove modal from DOM
            this.currentModal.remove();
            this.currentModal = null;
            
            // Clear expanded sections
            this.expandedSections.clear();
        }
    }

    toggleLogSource(clientId, logSource) {
        const sectionId = `logs-${logSource}`;
        const content = document.getElementById(sectionId);
        const header = content.previousElementSibling;
        const toggle = header.querySelector('.accordion-toggle');
        
        if (this.expandedSections.has(logSource)) {
            // Collapse
            content.classList.remove('expanded');
            toggle.classList.remove('expanded');
            this.expandedSections.delete(logSource);
            console.log(`Collapsed log section: ${logSource}`);
        } else {
            // Expand
            content.classList.add('expanded');
            toggle.classList.add('expanded');
            this.expandedSections.add(logSource);
            console.log(`Expanded log section: ${logSource}`);
            
            // Trigger HTMX load if not already loaded
            if (window.htmx && !content.hasAttribute('hx-loaded')) {
                htmx.trigger(content, 'load');
                content.setAttribute('hx-loaded', 'true');
            }
        }
    }

    filterLogsBySeverity(severity) {
        if (!this.currentModal) return;

        console.log(`Filtering logs by severity: ${severity || 'all levels'}`);

        // Get all log entries in the modal
        const logEntries = this.currentModal.querySelectorAll('.log-entry');
        const allowedSeverities = severity ? severity.split(',') : [];

        let visibleCounts = {};

        logEntries.forEach(entry => {
            const entrySeverity = entry.querySelector('.log-severity')?.textContent?.trim();
            const shouldShow = allowedSeverities.length === 0 || 
                             allowedSeverities.includes(entrySeverity);

            if (shouldShow) {
                entry.classList.remove('filtered-hidden');
                
                // Count visible entries per accordion
                const accordion = entry.closest('.accordion-content');
                if (accordion) {
                    const accordionId = accordion.id;
                    visibleCounts[accordionId] = (visibleCounts[accordionId] || 0) + 1;
                }
            } else {
                entry.classList.add('filtered-hidden');
            }
        });

        // Update accordion sections based on visible entries
        this.currentModal.querySelectorAll('.accordion-content').forEach(accordion => {
            const accordionId = accordion.id;
            const visibleCount = visibleCounts[accordionId] || 0;
            const logEntriesContainer = accordion.querySelector('.log-entries');
            
            if (logEntriesContainer) {
                if (visibleCount === 0) {
                    // Show "no entries" message
                    let noEntriesMsg = accordion.querySelector('.no-filtered-entries');
                    if (!noEntriesMsg) {
                        noEntriesMsg = document.createElement('div');
                        noEntriesMsg.className = 'no-filtered-entries accordion-content no-visible-logs';
                        noEntriesMsg.textContent = severity ? 
                            `No ${severity} entries found for this log source.` : 
                            'No entries found.';
                        accordion.appendChild(noEntriesMsg);
                    }
                    noEntriesMsg.style.display = 'block';
                    logEntriesContainer.style.display = 'none';
                } else {
                    // Hide "no entries" message and show entries
                    const noEntriesMsg = accordion.querySelector('.no-filtered-entries');
                    if (noEntriesMsg) {
                        noEntriesMsg.style.display = 'none';
                    }
                    logEntriesContainer.style.display = 'block';
                }
            }
        });
    }

    showLoading() {
        const loadingHtml = `
            <div class="modal-overlay" id="client-modal-loading">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Loading Client Details...</h3>
                        <button class="modal-close-btn" onclick="closeClientModal()">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div class="loading-container">
                            <div class="spinner"></div>
                            <p>Fetching client information...</p>
                        </div>
                    </div>
                </div>
            </div>
            <style>
                .loading-container {
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    padding: 2rem;
                }
                
                .spinner {
                    width: 40px;
                    height: 40px;
                    border: 4px solid var(--border-color);
                    border-top: 4px solid var(--accent-color);
                    border-radius: 50%;
                    animation: spin 1s linear infinite;
                    margin-bottom: 1rem;
                }
                
                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
                
                .loading-container p {
                    color: var(--text-secondary);
                    margin: 0;
                }
            </style>
        `;
        
        document.body.insertAdjacentHTML('beforeend', loadingHtml);
        this.currentModal = document.getElementById('client-modal-loading');
        document.body.style.overflow = 'hidden';
    }

    removeLoading() {
        const loading = document.getElementById('client-modal-loading');
        if (loading) {
            loading.remove();
        }
        this.currentModal = null;
    }

    showError(message) {
        const errorHtml = `
            <div class="modal-overlay" id="client-modal-error">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Error</h3>
                        <button class="modal-close-btn" onclick="closeClientModal()">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div class="error-message">
                            ${message}
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.insertAdjacentHTML('beforeend', errorHtml);
        this.currentModal = document.getElementById('client-modal-error');
        document.body.style.overflow = 'hidden';
    }

    switchTab(tabId) {
        if (!this.currentModal) return;

        // Remove active class from all tabs and buttons
        const tabBtns = this.currentModal.querySelectorAll('.tab-btn');
        const tabContents = this.currentModal.querySelectorAll('.tab-content');

        tabBtns.forEach(btn => btn.classList.remove('active'));
        tabContents.forEach(content => content.classList.remove('active'));

        // Add active class to selected tab button and content
        const activeBtn = this.currentModal.querySelector(`[onclick="switchTab('${tabId}')"]`);
        const activeContent = this.currentModal.querySelector(`#${tabId}`);

        if (activeBtn && activeContent) {
            activeBtn.classList.add('active');
            activeContent.classList.add('active');
            console.log(`Switched to tab: ${tabId}`);
        }
    }

    async setFanMode(mode, clientId) {
        try {
            console.log(`Setting fan mode to ${mode} for client ${clientId}`);
            const response = await fetch(`/api/commands`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    client_id: clientId,
                    command_type: "fan_control",
                    command_data: { action: "set_mode", mode: mode }
                })
            });

            const result = await response.json();
            this.displayCommandResult(`Fan Mode: ${mode}`, result);

        } catch (error) {
            console.error('Error setting fan mode:', error);
            this.displayCommandResult(`Fan Mode: ${mode}`, { error: error.message });
        }
    }

    async getFanStatus(clientId) {
        try {
            console.log(`Getting fan status for client ${clientId}`);
            const response = await fetch(`/api/commands`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    client_id: clientId,
                    command_type: "fan_control",
                    command_data: { action: "get_status" }
                })
            });
            const result = await response.json();
            this.displayCommandResult('Fan Status', result);

        } catch (error) {
            console.error('Error getting fan status:', error);
            this.displayCommandResult('Fan Status', { error: error.message });
        }
    }

    async setFanSpeeds(speed, clientId) {
        try {
            console.log(`Setting fan speeds to ${speed}% for client ${clientId}`);
            const response = await fetch(`/api/commands`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    client_id: clientId,
                    command_type: "fan_control",
                    command_data: { 
                        action: "set_fan_speeds", 
                        zone0_speed: speed, 
                        zone1_speed: speed 
                    }
                })
            });

            const result = await response.json();
            this.displayCommandResult(`Fan Speed: ${speed}%`, result);

        } catch (error) {
            console.error('Error setting fan speeds:', error);
            this.displayCommandResult(`Fan Speed: ${speed}%`, { error: error.message });
        }
    }

    setCustomFanSpeed(clientId) {
        const inputElement = document.getElementById(`custom-speed-${clientId}`);
        const speed = parseInt(inputElement.value);
        
        // Validate input
        if (!speed || speed < 20 || speed > 100) {
            this.displayCommandResult('Custom Fan Speed', { 
                error: 'Invalid speed. Please enter a value between 20-100%' 
            });
            return;
        }

        // Clear input and set speed
        inputElement.value = '';
        this.setFanSpeeds(speed, clientId);
    }

    async getSystemInfo(type, clientId) {
        try {
            console.log(`Getting system info (${type}) for client ${clientId}`);
            const response = await fetch(`/api/commands`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    client_id: clientId,
                    command_type: "system_info",
                    command_data: { type: type }
                })
            });
            const result = await response.json();
            this.displayCommandResult(`System Info (${type})`, result);

        } catch (error) {
            console.error('Error getting system info:', error);
            this.displayCommandResult(`System Info (${type})`, { error: error.message });
        }
    }

    async executeCustomIPMI(clientId) {
        try {
            const input = this.currentModal.querySelector(`#ipmi-raw-input-${clientId}`);
            if (!input || !input.value.trim()) {
                this.displayCommandResult('IPMI Command', { error: 'Please enter a command' });
                return;
            }

            const command = input.value.trim();
            console.log(`Executing IPMI command "${command}" for client ${clientId}`);
            
            const response = await fetch(`/api/commands`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    client_id: clientId,
                    command_type: "ipmi_raw",
                    command_data: { command: command }
                })
            });

            const result = await response.json();
            this.displayCommandResult(`IPMI: ${command}`, result);
            
            // Clear input after execution
            input.value = '';

        } catch (error) {
            console.error('Error executing IPMI command:', error);
            this.displayCommandResult('IPMI Command', { error: error.message });
        }
    }

    displayCommandResult(command, result) {
        if (!this.currentModal) return;

        const resultsContainer = this.currentModal.querySelector('.results-container');
        if (!resultsContainer) return;

        // Remove "no results" message if present
        const noResults = resultsContainer.querySelector('.no-results');
        if (noResults) {
            noResults.remove();
        }

        // Create result element
        const resultElement = document.createElement('div');
        resultElement.className = 'command-result';
        
        const timestamp = new Date().toLocaleTimeString();
        const success = !result.error;
        
        resultElement.innerHTML = `
            <div class="result-header ${success ? 'success' : 'error'}">
                <span class="result-command">${command}</span>
                <span class="result-time">${timestamp}</span>
            </div>
            <div class="result-body">
                ${success ? 
                    `<pre>${JSON.stringify(result, null, 2)}</pre>` : 
                    `<div class="error-text">${result.error}</div>`
                }
            </div>
        `;

        // Add to top of results
        resultsContainer.insertBefore(resultElement, resultsContainer.firstChild);

        // Limit to 10 results
        const results = resultsContainer.querySelectorAll('.command-result');
        if (results.length > 10) {
            results[results.length - 1].remove();
        }

        // Scroll to top
        resultsContainer.scrollTop = 0;
        
        console.log(`Command result displayed: ${command}`);
    }
}

// Global instance
window.clientDetailModal = new ClientDetailModal();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ClientDetailModal;
}