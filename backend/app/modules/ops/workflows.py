"""Temporal workflow stubs for Ops module (Phase 8)."""

from __future__ import annotations


class BillingEnforcementSweepWorkflow:
    """Temporal workflow stub — sweeps all tenants for quota enforcement."""

    async def run(self) -> None:
        raise NotImplementedError("BillingEnforcementSweepWorkflow requires Temporal")


class StatusPageSyncWorkflow:
    """Temporal workflow stub — syncs component health to status page."""

    async def run(self) -> None:
        raise NotImplementedError("StatusPageSyncWorkflow requires Temporal")


class DRBackupValidationWorkflow:
    """Temporal workflow stub — validates DR backup integrity."""

    async def run(self, backup_id: str) -> None:
        raise NotImplementedError("DRBackupValidationWorkflow requires Temporal")
