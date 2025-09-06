#!/usr/bin/env python3
"""
dcmon API Dependencies - Authentication and Dependency Injection
"""

import base64
import logging
from secrets import compare_digest
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Support running as script or as package
try:
    from ..models import Client
    from ..core.audit import audit_logger
except ImportError:
    from models import Client
    from core.audit import audit_logger

logger = logging.getLogger("dcmon.server")
security = HTTPBearer(auto_error=False)


class AuthDependencies:
    """Container for authentication dependencies with admin token."""
    
    def __init__(self, admin_token: Optional[str], test_mode: bool = False):
        self.admin_token = admin_token
        self.test_mode = test_mode
    
    def require_admin_auth(self, request: Request) -> None:
        """
        Simple Basic Auth for both test and production modes.
        In test mode, use any username + dev_admin_token_12345 as password.
        In production mode, use any username + real admin token as password.
        """
        auth_header = request.headers.get("authorization", "")
        
        if auth_header.startswith("Basic "):
            try:
                credentials = base64.b64decode(auth_header[6:]).decode('utf-8')
                if ":" in credentials:
                    username, password = credentials.split(":", 1)
                    if self.admin_token and compare_digest(password, self.admin_token):
                        logger.debug("Admin authenticated via Basic Auth")
                        # Log successful admin authentication
                        audit_logger.auth_attempt(
                            success=True,
                            auth_type="admin_basic",
                            details={"username": username, "test_mode": self.test_mode},
                            request=request
                        )
                        return
            except Exception as e:
                logger.debug(f"Basic Auth parsing failed: {e}")
        
        # Log failed admin authentication attempt
        audit_logger.auth_attempt(
            success=False,
            auth_type="admin_basic", 
            details={"reason": "invalid_credentials", "test_mode": self.test_mode},
            request=request
        )
        
        # Authentication failed - prompt for Basic Auth
        realm_msg = "dcmon Admin (test mode: use any username + dev_admin_token_12345)" if self.test_mode else "dcmon Admin"
        logger.warning("Admin authentication failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": f"Basic realm=\"{realm_msg}\""}
        )
    
    def require_client_auth(self, request: Request, creds: HTTPAuthorizationCredentials = Depends(security)) -> Client:
        """Authenticate client by token and return Client object."""
        token = creds.credentials
        client = Client.get_by_token(token)
        
        if not client:
            # Log failed client authentication to audit system
            audit_logger.auth_attempt(
                success=False,
                auth_type="client_bearer", 
                details={"token_prefix": token[:8], "endpoint": str(request.url)},
                request=request
            )
            logger.warning(f"Client authentication failed with token: {token[:8]}...")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid client token")
        
        # Log successful client auth (less verbose, just for security monitoring)
        if logger.isEnabledFor(logging.DEBUG):
            audit_logger.auth_attempt(
                success=True, 
                auth_type="client_bearer",
                details={"client_id": client.id, "hostname": client.hostname, "endpoint": str(request.url)},
                request=request
            )
        
        return client