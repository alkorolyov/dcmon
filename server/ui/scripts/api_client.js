/**
 * API Client - Utilities for making API calls
 * 
 * Handles authentication, error handling, and standardized API communication
 */

class ApiClient {
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
        this.defaultHeaders = {
            'Content-Type': 'application/json',
        };
    }
    
    /**
     * Make authenticated API request
     */
    async request(endpoint, options = {}) {
        const url = this.baseUrl + endpoint;
        const config = {
            method: 'GET',
            headers: { ...this.defaultHeaders },
            ...options
        };
        
        // Add request body if provided
        if (config.body && typeof config.body === 'object') {
            config.body = JSON.stringify(config.body);
        }
        
        try {
            const response = await fetch(url, config);
            
            // Handle authentication errors
            if (response.status === 401) {
                this.handleAuthError();
                throw new Error('Authentication required');
            }
            
            // Handle other errors
            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`HTTP ${response.status}: ${errorText || response.statusText}`);
            }
            
            // Parse JSON response
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return await response.json();
            } else {
                return await response.text();
            }
            
        } catch (error) {
            console.error(`API request failed: ${config.method} ${url}`, error);
            throw error;
        }
    }
    
    /**
     * GET request
     */
    async get(endpoint, params = null) {
        let url = endpoint;
        if (params) {
            const searchParams = new URLSearchParams();
            for (const [key, value] of Object.entries(params)) {
                if (Array.isArray(value)) {
                    value.forEach(v => searchParams.append(key, v));
                } else if (value !== null && value !== undefined) {
                    searchParams.set(key, value);
                }
            }
            if (searchParams.toString()) {
                url += '?' + searchParams.toString();
            }
        }
        
        return this.request(url, { method: 'GET' });
    }
    
    /**
     * POST request
     */
    async post(endpoint, data = null) {
        return this.request(endpoint, {
            method: 'POST',
            body: data
        });
    }
    
    /**
     * PUT request
     */
    async put(endpoint, data = null) {
        return this.request(endpoint, {
            method: 'PUT',
            body: data
        });
    }
    
    /**
     * DELETE request
     */
    async delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }
    
    /**
     * Handle authentication errors
     */
    handleAuthError() {
        // Dashboard uses Basic Auth - redirect to login
        console.warn('Authentication failed, redirecting to login...');
        // Could trigger a modal or redirect as needed
    }
    
    /**
     * Get timeseries data for a specific metric
     */
    async getTimeseries(metricName, params = {}) {
        return this.get(`/api/timeseries/${metricName}`, {
            hours: 24,
            aggregation: 'max',
            ...params
        });
    }
    
    /**
     * Get client list
     */
    async getClients() {
        return this.get('/api/clients');
    }
    
    /**
     * Get server stats
     */
    async getStats() {
        return this.get('/api/stats');
    }
    
    /**
     * Get server health
     */
    async getHealth() {
        return this.get('/health');
    }
    
    /**
     * Create a command for a client
     */
    async createCommand(machineId, commandType, commandData) {
        return this.post('/api/commands', {
            machine_id: machineId,
            command_type: commandType,
            command_data: commandData
        });
    }
}

// Create global API client instance
window.apiClient = new ApiClient();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ApiClient;
}