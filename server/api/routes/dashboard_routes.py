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
    from ...web.template_helpers import setup_template_filters
except ImportError:
    from dashboard import DashboardController
    from dashboard.controller import TABLE_COLUMNS
    from api.dependencies import AuthDependencies
    from web.template_helpers import setup_template_filters

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


    return router