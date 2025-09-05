#!/usr/bin/env python3
"""
Authentication Routes - Registration and Client Verification
"""

import logging
from fastapi import APIRouter, Depends, HTTPException

# Support running as script or as package
try:
    from ...models import db_manager, Client
    from ...auth import AuthService
    from ..schemas import RegistrationRequest
    from ..dependencies import AuthDependencies
except ImportError:
    from models import db_manager, Client
    from auth import AuthService
    from api.schemas import RegistrationRequest
    from api.dependencies import AuthDependencies

logger = logging.getLogger("dcmon.server")


def create_auth_routes(auth_deps: AuthDependencies) -> APIRouter:
    """Create authentication-related routes."""
    router = APIRouter()
    auth_service = AuthService()

    @router.post("/api/clients/register", status_code=201, dependencies=[Depends(auth_deps.require_admin_auth)])
    def register_client(request: RegistrationRequest):
        """Register a new client using RSA key-based authentication."""
        vr = auth_service.validate_registration_request(request.model_dump())
        if not vr.get("valid"):
            raise HTTPException(status_code=422, detail=vr.get("error") or "invalid request")

        # Check if client with this machine_id already exists
        existing_client = Client.get_by_machine_id(request.machine_id)
        if existing_client:
            # Update last_seen and return existing client
            existing_client.update_last_seen()
            logger.info(f"EXISTING CLIENT: {request.hostname} (machine_id: {request.machine_id[:8]}...) - returned existing client_id: {existing_client.id}")
            return {
                "client_id": existing_client.id, 
                "client_token": existing_client.client_token,
                "message": "Client already registered, using existing token"
            }

        client_token = auth_service.generate_client_token()
        client_id = db_manager.register_client(
            hostname=vr["hostname"],
            client_token=client_token,
            machine_id=request.machine_id,
            hw_hash=request.hw_hash,
            public_key=vr["public_key"],
            # Hardware inventory
            mdb_name=request.mdb_name,
            cpu_name=request.cpu_name,
            gpu_name=request.gpu_name,
            gpu_count=request.gpu_count,
            ram_gb=request.ram_gb,
            cpu_cores=request.cpu_cores,
            drives=request.drives,
        )
        if client_id is None:
            raise HTTPException(status_code=500, detail="failed to register client")

        logger.info(f"NEW CLIENT: {request.hostname} (machine_id: {request.machine_id[:8]}...) - client_id: {client_id}")
        
        return {"client_id": client_id, "client_token": client_token}

    @router.get("/api/client/verify")
    def verify_client(client: Client = Depends(auth_deps.require_client_auth)):
        """Verify client authentication and return client info."""
        return {
            "status": "authenticated",
            "client_id": client.id,
            "hostname": client.hostname,
            "last_seen": client.last_seen
        }

    return router