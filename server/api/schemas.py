#!/usr/bin/env python3
"""
dcmon API Schemas - Pydantic Models for Request/Response Validation
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class RegistrationRequest(BaseModel):
    hostname: str
    public_key: str
    challenge: str
    signature: str
    timestamp: int
    # System identification
    machine_id: str
    hw_hash: Optional[str] = None
    # Hardware inventory fields (optional)
    mdb_name: Optional[str] = None
    cpu_name: Optional[str] = None
    gpu_name: Optional[str] = None
    gpu_count: Optional[int] = None
    ram_gb: Optional[int] = None
    cpu_cores: Optional[int] = None
    drives: Optional[List[Dict[str, Any]]] = None
    # Vast.ai specific fields
    vast_machine_id: Optional[str] = None
    vast_port_range: Optional[str] = None


class MetricRecord(BaseModel):
    timestamp: int
    metric_name: str = Field(..., min_length=1)
    value: float  # All values stored as float
    labels: Optional[Dict[str, Any]] = None


class LogEntryData(BaseModel):
    log_source: str = Field(..., pattern="^(dmesg|journal|syslog|vast)$")
    log_timestamp: int
    content: str = Field(..., min_length=1)
    severity: Optional[str] = Field(None, pattern="^(ERROR|WARN|INFO|DEBUG)$")


class MetricsBatchRequest(BaseModel):
    metrics: List[MetricRecord]
    logs: Optional[List[LogEntryData]] = []
    hw_hash: Optional[str] = None


