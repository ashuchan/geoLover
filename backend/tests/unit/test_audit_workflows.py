"""Unit tests for Audit workflow stubs."""

from __future__ import annotations

import uuid
import pytest

from app.modules.audit.workflows import (
    AuditWorkflow,
    AuditWorkflowInput,
    AuditWorkflowResult,
    RedetectAuditWorkflow,
    RedetectWorkflowInput,
    RedetectWorkflowResult,
    WorkflowStatus,
)


class TestWorkflowDataclasses:
    def test_audit_workflow_input(self):
        inp = AuditWorkflowInput(
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            trigger="manual",
        )
        assert inp.algorithm_version == "v1"
        assert inp.max_queries == 50

    def test_audit_workflow_result(self):
        r = AuditWorkflowResult(
            audit_run_id=uuid.uuid4(),
            status=WorkflowStatus.completed,
            ai_visibility_score=75.0,
        )
        assert r.status == WorkflowStatus.completed
        assert r.ai_visibility_score == 75.0

    def test_redetect_input(self):
        r = RedetectWorkflowInput(
            original_audit_run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        )
        assert r.algorithm_version == "v1"

    def test_redetect_result(self):
        r = RedetectWorkflowResult(
            new_audit_run_id=uuid.uuid4(),
            status=WorkflowStatus.failed,
            error_message="Something went wrong",
        )
        assert r.error_message == "Something went wrong"

    def test_workflow_status_enum_values(self):
        assert WorkflowStatus.pending.value == "pending"
        assert WorkflowStatus.running.value == "running"
        assert WorkflowStatus.completed.value == "completed"
        assert WorkflowStatus.failed.value == "failed"


class TestAuditWorkflowStub:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = AuditWorkflow()
        with pytest.raises(NotImplementedError, match="Temporal"):
            await wf.run(
                AuditWorkflowInput(
                    business_id=uuid.uuid4(),
                    tenant_id=uuid.uuid4(),
                    trigger="manual",
                )
            )


class TestRedetectWorkflowStub:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = RedetectAuditWorkflow()
        with pytest.raises(NotImplementedError, match="Temporal"):
            await wf.run(
                RedetectWorkflowInput(
                    original_audit_run_id=uuid.uuid4(),
                    tenant_id=uuid.uuid4(),
                )
            )
