#!/usr/bin/env python3
"""
dcmon Security Audit Logger

Provides structured logging for authentication attempts and admin actions.
"""

import json
import logging
import time
from typing import Dict, Any, Optional
from fastapi import Request


class AuditLogger:
    """Centralized audit logging for security events."""
    
    def __init__(self):
        self.logger = logging.getLogger("dcmon.audit")
        
    def _log_event(self, event_type: str, details: Dict[str, Any], request: Optional[Request] = None):
        """Log a structured audit event."""
        audit_record = {
            "timestamp": int(time.time()),
            "event_type": event_type,
            "details": details
        }
        
        # Add request context if available
        if request:
            client_ip = request.client.host if request.client else "unknown"
            user_agent = request.headers.get("user-agent", "unknown")
            audit_record.update({
                "client_ip": client_ip,
                "user_agent": user_agent,
                "method": request.method,
                "url": str(request.url)
            })
        
        # Log as JSON for structured parsing
        self.logger.info(json.dumps(audit_record))
    
    def auth_attempt(self, success: bool, auth_type: str, details: Dict[str, Any], request: Optional[Request] = None):
        """Log authentication attempt."""
        self._log_event(
            event_type="auth_attempt",
            details={
                "success": success,
                "auth_type": auth_type,  # "admin_basic", "client_bearer", "registration"
                **details
            },
            request=request
        )
    
    def admin_action(self, action: str, details: Dict[str, Any], request: Optional[Request] = None):
        """Log admin action."""
        self._log_event(
            event_type="admin_action", 
            details={
                "action": action,  # "dashboard_access", "client_list", "command_create", etc.
                **details
            },
            request=request
        )
    
    def client_registration(self, success: bool, hostname: str, machine_id: str, 
                           details: Dict[str, Any], request: Optional[Request] = None):
        """Log client registration attempt."""
        self._log_event(
            event_type="client_registration",
            details={
                "success": success,
                "hostname": hostname,
                "machine_id": machine_id[:12],  # Truncate for privacy
                **details
            },
            request=request
        )


# Global audit logger instance
audit_logger = AuditLogger()