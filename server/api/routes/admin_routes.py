#!/usr/bin/env python3
"""
Admin Routes - Client Management, Stats, and Health Checks
"""

import logging
from fastapi import APIRouter, Depends, Request

# Support running as script or as package
try:
    from ...models import db_manager, Client
    from ..dependencies import AuthDependencies
    from ...core.audit import audit_logger
except ImportError:
    from models import db_manager, Client
    from api.dependencies import AuthDependencies
    from core.audit import audit_logger

logger = logging.getLogger("dcmon.server")


def create_admin_routes(auth_deps: AuthDependencies) -> APIRouter:
    """Create admin-only routes."""
    router = APIRouter()

    @router.get("/api/clients", dependencies=[Depends(auth_deps.require_admin_auth)])
    def list_clients(request: Request):
        """Get list of all registered clients (admin only)."""
        items = []
        for c in Client.select().order_by(Client.last_seen.desc(nulls="LAST")):
            items.append(c.to_dict())
        
        # Log admin action
        audit_logger.admin_action(
            action="list_clients",
            details={"client_count": len(items)},
            request=request
        )
        
        return {"clients": items}

    @router.get("/api/stats", dependencies=[Depends(auth_deps.require_admin_auth)])
    def get_stats(request: Request):
        """Get server statistics (admin only)."""
        stats = db_manager.get_stats()
        
        # Log admin action
        audit_logger.admin_action(
            action="get_stats",
            details={"stats_requested": list(stats.keys()) if stats else []},
            request=request
        )
        
        return stats

    @router.get("/health", dependencies=[Depends(auth_deps.require_admin_auth)])
    def health(request: Request):
        """Health check endpoint (admin only)."""
        # Log admin action
        audit_logger.admin_action(
            action="health_check",
            details={},
            request=request
        )
        try:
            Client.select().limit(1).execute()
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "ok", "db": "connected" if db_ok else "down"}

    return router