#!/usr/bin/env python3
"""
Admin Routes - Client Management, Stats, and Health Checks
"""

import logging
from fastapi import APIRouter, Depends

# Support running as script or as package
try:
    from ...models import db_manager, Client
    from ..dependencies import AuthDependencies
except ImportError:
    from models import db_manager, Client
    from api.dependencies import AuthDependencies

logger = logging.getLogger("dcmon.server")


def create_admin_routes(auth_deps: AuthDependencies) -> APIRouter:
    """Create admin-only routes."""
    router = APIRouter()

    @router.get("/api/clients", dependencies=[Depends(auth_deps.require_admin_auth)])
    def list_clients():
        """Get list of all registered clients (admin only)."""
        items = []
        for c in Client.select().order_by(Client.last_seen.desc(nulls="LAST")):
            items.append(c.to_dict())
        return {"clients": items}

    @router.get("/api/stats", dependencies=[Depends(auth_deps.require_admin_auth)])
    def get_stats():
        """Get server statistics (admin only)."""
        return db_manager.get_stats()

    @router.get("/health", dependencies=[Depends(auth_deps.require_admin_auth)])
    def health():
        """Health check endpoint (admin only)."""
        try:
            Client.select().limit(1).execute()
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "ok", "db": "connected" if db_ok else "down"}

    return router