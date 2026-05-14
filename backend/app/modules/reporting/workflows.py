"""Reporting workflow stubs (Temporal activities implemented in Phase 3).

Real Temporal SDK integration comes in a later hardening phase.
These stubs define the interface and raise NotImplementedError.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from typing import Optional


class WorkflowStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


@dataclass
class ReportGenerationInput:
    audit_run_id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    template_version: str = "v1"
    workflow_run_id: Optional[str] = None


@dataclass
class ReportGenerationResult:
    report_id: uuid.UUID
    status: WorkflowStatus
    web_view_token: str
    pdf_gcs_uri: Optional[str] = None
    error_message: Optional[str] = None


class ReportGenerationWorkflow:
    """Orchestrates: load data → generate Quick Wins → render HTML → render PDF → persist Report."""

    async def run(self, input: ReportGenerationInput) -> ReportGenerationResult:
        raise NotImplementedError(
            "ReportGenerationWorkflow requires Temporal worker; not available in this environment"
        )
