#!/usr/bin/env python3
"""
Command Routes - Remote Command Management
"""

import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Path, status

# Support running as script or as package
try:
    from ...models import Client, Command
    from ..schemas import CommandResultRequest
    from ..dependencies import AuthDependencies
except ImportError:
    from models import Client, Command
    from api.schemas import CommandResultRequest
    from api.dependencies import AuthDependencies

logger = logging.getLogger("dcmon.server")


def create_command_routes(auth_deps: AuthDependencies) -> APIRouter:
    """Create command management routes."""
    router = APIRouter()

    @router.get("/api/commands/{client_id}")
    def get_client_commands(
        client_id: int = Path(..., ge=1),
        client: Client = Depends(auth_deps.require_client_auth),
    ):
        """Get pending commands for a client."""
        if client.id != client_id:
            raise HTTPException(status_code=403, detail="token does not belong to requested client_id")

        cmds = Command.get_pending_for_client(client_id)
        out = []
        for c in cmds:
            try:
                data = json.loads(c.command_data)
            except Exception:
                data = c.command_data
            out.append({
                "id": c.id,
                "client_id": client_id,
                "command_type": c.command_type,
                "command_data": data,
                "status": c.status,
                "created_at": c.created_at,
            })
        return {"commands": out}

    @router.post("/api/command-results")
    def submit_command_result(body: CommandResultRequest, client: Client = Depends(auth_deps.require_client_auth)):
        """Submit command execution result from client."""
        try:
            cmd = Command.get_by_id(body.command_id)
        except Command.DoesNotExist:
            raise HTTPException(status_code=404, detail="command not found")

        if (isinstance(cmd.client, Client) and cmd.client.id != client.id) or \
           (not isinstance(cmd.client, Client) and int(cmd.client) != client.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="command not owned by this client")

        if body.status == "completed":
            cmd.mark_completed(result=body.result or {})
        else:
            err = ""
            if body.result and "error" in body.result:
                err = str(body.result["error"])
            elif body.result is not None:
                err = json.dumps(body.result)
            else:
                err = "unknown error"
            cmd.mark_failed(error=err)

        return {"ok": True}

    return router