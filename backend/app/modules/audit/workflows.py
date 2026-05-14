"""Temporal workflow stubs for the Audit module.

These stubs define the workflow interface without requiring Temporal SDK.
In production, replace with real @workflow.defn / @activity.defn decorators.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class WorkflowStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


@dataclass
class AuditWorkflowInput:
    business_id: uuid.UUID
    tenant_id: uuid.UUID
    trigger: str  # AuditTrigger value
    template_set_id: Optional[uuid.UUID] = None
    algorithm_version: str = "v1"
    max_queries: int = 50


@dataclass
class AuditWorkflowResult:
    audit_run_id: uuid.UUID
    status: WorkflowStatus
    ai_visibility_score: Optional[float] = None
    completeness_pct: Optional[float] = None
    error_message: Optional[str] = None


class AuditWorkflow:
    """Temporal workflow stub for orchestrating audit runs.

    Workflow steps:
    1. Load BusinessIdentity
    2. Resolve template_set + generate queries
    3. Resolve healthy engines from registry
    4. Create AuditRun record (status='running')
    5. Fan-out: for each (engine, query_batch), execute probe
    6. Aggregate results
    7. Compute AIVisibilityScore
    8. Roll up CompetitorObservations
    9. Finalise AuditRun
    10. Emit domain event AuditRunCompleted
    """

    async def run(self, input: AuditWorkflowInput) -> AuditWorkflowResult:
        raise NotImplementedError(
            "AuditWorkflow.run must be implemented with Temporal SDK in production"
        )


@dataclass
class RedetectWorkflowInput:
    original_audit_run_id: uuid.UUID
    tenant_id: uuid.UUID
    algorithm_version: str = "v1"


@dataclass
class RedetectWorkflowResult:
    new_audit_run_id: uuid.UUID
    status: WorkflowStatus
    error_message: Optional[str] = None


class RedetectAuditWorkflow:
    """Re-run citation detection on archived GCS responses under a new algorithm version."""

    async def run(self, input: RedetectWorkflowInput) -> RedetectWorkflowResult:
        raise NotImplementedError(
            "RedetectAuditWorkflow.run must be implemented with Temporal SDK in production"
        )
