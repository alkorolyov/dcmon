#!/usr/bin/env python3
"""
Dashboard Routes - Web UI and Template Rendering
"""

import logging
import time
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

# Support running as script or as package
try:
    from ...dashboard import DashboardController
    from ...dashboard.controller import TABLE_COLUMNS
    from ..dependencies import AuthDependencies
    from ...dashboard.filters import setup_template_filters
    from ...core.audit import audit_logger
except ImportError:
    from dashboard import DashboardController
    from dashboard.controller import TABLE_COLUMNS
    from api.dependencies import AuthDependencies
    from dashboard.filters import setup_template_filters
    from core.audit import audit_logger

logger = logging.getLogger("dcmon.server")


def create_dashboard_routes(auth_deps: AuthDependencies) -> APIRouter:
    """Create dashboard and web UI routes."""
    router = APIRouter()
    
    # Initialize dashboard controller and templates
    dashboard_controller = DashboardController()
    templates = Jinja2Templates(directory=["ui/pages", "ui/components", "ui"])
    
    # Setup template filters
    setup_template_filters(templates)

    @router.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(auth_deps.require_admin_auth)])
    def dashboard_main(request: Request):
        """Main dashboard page - shows system overview, clients, and metrics."""
        logger.debug("Rendering main dashboard")
        
        # Log admin dashboard access
        audit_logger.admin_action(
            action="dashboard_access",
            details={"page": "main"},
            request=request
        )
        
        try:
            dashboard_data = dashboard_controller.get_main_dashboard_data()
            dashboard_data["request"] = request
            
            return templates.TemplateResponse("dashboard.html", dashboard_data)
            
        except Exception as e:
            logger.error(f"Dashboard error: {e}")
            return templates.TemplateResponse("dashboard.html", {
                "request": request,
                "page_title": "dcmon Dashboard - Error",
                "error": str(e),
                "timestamp": int(time.time()),
                "clients": [],
                "system_overview": {},
                "recent_alerts": [],
                "charts": {}
            })

    @router.get("/dashboard/refresh/clients", response_class=HTMLResponse, dependencies=[Depends(auth_deps.require_admin_auth)])
    def dashboard_refresh_clients(request: Request):
        """Refresh client status table via htmx."""
        logger.debug("Refreshing client status")
        
        # Log admin action (refresh clients table)
        audit_logger.admin_action(
            action="refresh_clients_table",
            details={"component": "htmx"},
            request=request
        )
        
        try:
            clients = dashboard_controller._get_client_status_data()
            return templates.TemplateResponse("tables/clients_table.html", {
                "request": request,
                "clients": clients,
                "timestamp": int(time.time()),
                "table_columns": TABLE_COLUMNS
            })
            
        except Exception as e:
            logger.error(f"Client refresh error: {e}")
            return templates.TemplateResponse("tables/clients_table.html", {
                "request": request,
                "clients": [],
                "error": str(e),
                "timestamp": int(time.time())
            })

    @router.get("/dashboard/client/{client_id}/modal", response_class=HTMLResponse, dependencies=[Depends(auth_deps.require_admin_auth)])
    def get_client_detail_modal(client_id: int, request: Request):
        """Get client detail modal content."""
        logger.debug(f"Loading client detail modal for client {client_id}")
        
        # Log admin action
        audit_logger.admin_action(
            action="view_client_detail",
            details={"client_id": client_id},
            request=request
        )
        
        try:
            client_data = dashboard_controller.get_client_detail_data(client_id)
            return templates.TemplateResponse("modals/client_detail/modal.html", {
                "request": request,
                **client_data
            })

        except Exception as e:
            logger.error(f"Client detail modal error: {e}")
            return templates.TemplateResponse("modals/client_detail/modal.html", {
                "request": request,
                "client_id": client_id,
                "error": str(e),
                "timestamp": int(time.time())
            })

    @router.get("/dashboard/client/{client_id}/logs/{log_source}", response_class=HTMLResponse, dependencies=[Depends(auth_deps.require_admin_auth)])
    def refresh_client_logs(client_id: int, log_source: str, request: Request):
        """Refresh logs for a specific client and log source via htmx."""
        logger.debug(f"Refreshing logs for client {client_id}, source {log_source}")
        
        # Log admin action
        audit_logger.admin_action(
            action="refresh_client_logs",
            details={"client_id": client_id, "log_source": log_source},
            request=request
        )
        
        try:
            logs = dashboard_controller.get_client_logs(client_id, log_source)
            return templates.TemplateResponse("logs/log_entries.html", {
                "request": request,
                "logs": logs,
                "client_id": client_id,
                "log_source": log_source,
                "timestamp": int(time.time())
            })
            
        except Exception as e:
            logger.error(f"Log refresh error: {e}")
            return templates.TemplateResponse("logs/log_entries.html", {
                "request": request,
                "logs": [],
                "client_id": client_id,
                "log_source": log_source,
                "error": str(e),
                "timestamp": int(time.time())
            })


    return router