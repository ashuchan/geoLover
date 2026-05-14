"""Unit tests for Ops workflow stubs (Phase 8)."""

from __future__ import annotations

import pytest

from app.modules.ops.workflows import (
    BillingEnforcementSweepWorkflow,
    DRBackupValidationWorkflow,
    StatusPageSyncWorkflow,
)


class TestBillingEnforcementSweepWorkflow:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = BillingEnforcementSweepWorkflow()
        with pytest.raises(NotImplementedError, match="BillingEnforcementSweepWorkflow"):
            await wf.run()


class TestStatusPageSyncWorkflow:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = StatusPageSyncWorkflow()
        with pytest.raises(NotImplementedError, match="StatusPageSyncWorkflow"):
            await wf.run()


class TestDRBackupValidationWorkflow:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = DRBackupValidationWorkflow()
        with pytest.raises(NotImplementedError, match="DRBackupValidationWorkflow"):
            await wf.run(backup_id="backup-123")

    @pytest.mark.asyncio
    async def test_run_requires_backup_id(self):
        wf = DRBackupValidationWorkflow()
        with pytest.raises(NotImplementedError):
            await wf.run(backup_id="test-backup-456")
