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


class MetricRecord(BaseModel):
    timestamp: int
    metric_name: str = Field(..., min_length=1)
    value_type: str = Field(..., pattern="^(int|float)$")
    value: float  # Accept as float, will be cast to int if value_type is "int"
    labels: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _validate_value_type(self) -> "MetricRecord":
        if self.value_type == "int":
            # Validate that the value can be converted to int
            try:
                int(self.value)
            except (ValueError, OverflowError):
                raise ValueError(f"value {self.value} cannot be converted to integer")
        return self


class LogEntryData(BaseModel):
    log_source: str = Field(..., pattern="^(dmesg|journal|syslog|vast)$")
    log_timestamp: int
    content: str = Field(..., min_length=1)
    severity: Optional[str] = Field(None, pattern="^(ERROR|WARN|INFO|DEBUG)$")


class MetricsBatchRequest(BaseModel):
    metrics: List[MetricRecord]
    logs: Optional[List[LogEntryData]] = []
    hw_hash: Optional[str] = None


class CommandResultRequest(BaseModel):
    command_id: str
    status: str = Field("completed", pattern="^(completed|failed)$")
    result: Optional[Dict[str, Any]] = None