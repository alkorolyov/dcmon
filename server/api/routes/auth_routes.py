#!/usr/bin/env python3
"""
Authentication Routes - Registration and Client Verification
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request

# Support running as script or as package
try:
    from ...models import db_manager, Client
    from ...auth import AuthService
    from ..schemas import RegistrationRequest
    from ..dependencies import AuthDependencies
    from ...core.audit import audit_logger
except ImportError:
    from models import db_manager, Client
    from auth import AuthService
    from api.schemas import RegistrationRequest
    from api.dependencies import AuthDependencies
    from core.audit import audit_logger

logger = logging.getLogger("dcmon.server")


def create_auth_routes(auth_deps: AuthDependencies) -> APIRouter:
    """Create authentication-related routes."""
    router = APIRouter()
    auth_service = AuthService()

    @router.post("/api/clients/register", status_code=201, dependencies=[Depends(auth_deps.require_admin_auth)])
    def register_client(registration_request: RegistrationRequest, request: Request):
        """Register a new client using RSA key-based authentication."""
        vr = auth_service.validate_registration_request(registration_request.model_dump())
        if not vr.get("valid"):
            # Log failed registration attempt
            audit_logger.client_registration(
                success=False,
                hostname=registration_request.hostname,
                machine_id=registration_request.machine_id,
                details={"reason": vr.get("error") or "invalid request"},
                request=request
            )
            raise HTTPException(status_code=422, detail=vr.get("error") or "invalid request")

        # Check if client with this machine_id already exists
        existing_client = Client.get_by_machine_id(registration_request.machine_id)
        if existing_client:
            # Update last_seen and return existing client
            existing_client.update_last_seen()
            logger.info(f"EXISTING CLIENT: {registration_request.hostname} (machine_id: {registration_request.machine_id[:8]}...) - returned existing client_id: {existing_client.id}")
            
            # Log successful registration (existing client)
            audit_logger.client_registration(
                success=True,
                hostname=registration_request.hostname,
                machine_id=registration_request.machine_id,
                details={"action": "existing_client_returned", "client_id": existing_client.id},
                request=request
            )
            
            return {
                "client_id": existing_client.id, 
                "client_token": existing_client.client_token,
                "message": "Client already registered, using existing token"
            }

        client_token = auth_service.generate_client_token()
        client_id = db_manager.register_client(
            hostname=vr["hostname"],
            client_token=client_token,
            machine_id=registration_request.machine_id,
            hw_hash=registration_request.hw_hash,
            public_key=vr["public_key"],
            # Hardware inventory
            mdb_name=registration_request.mdb_name,
            cpu_name=registration_request.cpu_name,
            gpu_name=registration_request.gpu_name,
            gpu_count=registration_request.gpu_count,
            ram_gb=registration_request.ram_gb,
            cpu_cores=registration_request.cpu_cores,
            drives=registration_request.drives,
            # Vast.ai fields
            vast_machine_id=registration_request.vast_machine_id,
            vast_port_range=registration_request.vast_port_range,
        )
        if client_id is None:
            # Log failed registration (database error)
            audit_logger.client_registration(
                success=False,
                hostname=registration_request.hostname,
                machine_id=registration_request.machine_id,
                details={"reason": "database_error", "stage": "client_creation"},
                request=request
            )
            raise HTTPException(status_code=500, detail="failed to register client")

        logger.info(f"NEW CLIENT: {registration_request.hostname} (machine_id: {registration_request.machine_id[:8]}...) - client_id: {client_id}")
        
        # Log successful new client registration
        audit_logger.client_registration(
            success=True,
            hostname=registration_request.hostname,
            machine_id=registration_request.machine_id,
            details={"action": "new_client_registered", "client_id": client_id},
            request=request
        )
        
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