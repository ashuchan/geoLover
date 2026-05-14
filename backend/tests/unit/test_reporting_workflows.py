"""Unit tests for Reporting workflow stubs."""

from __future__ import annotations

import uuid

import pytest

from app.modules.reporting.workflows import (
    ReportGenerationInput,
    ReportGenerationResult,
    ReportGenerationWorkflow,
    WorkflowStatus,
)


class TestWorkflowStatusEnum:
    def test_values(self):
        assert WorkflowStatus.pending.value == "pending"
        assert WorkflowStatus.running.value == "running"
        assert WorkflowStatus.completed.value == "completed"
        assert WorkflowStatus.failed.value == "failed"


class TestReportGenerationInput:
    def test_dataclass_fields(self):
        inp = ReportGenerationInput(
            audit_run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
        )
        assert inp.template_version == "v1"
        assert inp.workflow_run_id is None

    def test_custom_values(self):
        arid = uuid.uuid4()
        tid = uuid.uuid4()
        bid = uuid.uuid4()
        inp = ReportGenerationInput(
            audit_run_id=arid,
            tenant_id=tid,
            business_id=bid,
            template_version="v2",
            workflow_run_id="wf-123",
        )
        assert inp.audit_run_id == arid
        assert inp.template_version == "v2"
        assert inp.workflow_run_id == "wf-123"


class TestReportGenerationResult:
    def test_dataclass_fields(self):
        rid = uuid.uuid4()
        result = ReportGenerationResult(
            report_id=rid,
            status=WorkflowStatus.completed,
            web_view_token="tok123",
        )
        assert result.report_id == rid
        assert result.status == WorkflowStatus.completed
        assert result.pdf_gcs_uri is None
        assert result.error_message is None

    def test_with_error(self):
        result = ReportGenerationResult(
            report_id=uuid.uuid4(),
            status=WorkflowStatus.failed,
            web_view_token="",
            error_message="LLM timeout",
        )
        assert result.status == WorkflowStatus.failed
        assert result.error_message == "LLM timeout"


class TestReportGenerationWorkflow:
    @pytest.mark.asyncio
    async def test_raises_not_implemented(self):
        workflow = ReportGenerationWorkflow()
        inp = ReportGenerationInput(
            audit_run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
        )
        with pytest.raises(NotImplementedError):
            await workflow.run(inp)
