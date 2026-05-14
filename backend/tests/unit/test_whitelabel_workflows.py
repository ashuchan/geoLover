"""Unit tests for whitelabel workflow stubs."""

from __future__ import annotations

import pytest

from app.modules.whitelabel.workflows import (
    BulkImportWorkflow,
    DNSHeartbeatWorkflow,
    ProvisionSSLWorkflow,
    VerifyDomainWorkflow,
    VerifyEmailSenderDomainWorkflow,
)


class TestVerifyDomainWorkflow:
    @pytest.mark.asyncio
    async def test_raises_not_implemented(self):
        wf = VerifyDomainWorkflow()
        with pytest.raises(NotImplementedError, match="Temporal"):
            await wf.run("mapping-id", "tenant-id")


class TestProvisionSSLWorkflow:
    @pytest.mark.asyncio
    async def test_raises_not_implemented(self):
        wf = ProvisionSSLWorkflow()
        with pytest.raises(NotImplementedError, match="Temporal"):
            await wf.run("mapping-id")


class TestBulkImportWorkflow:
    @pytest.mark.asyncio
    async def test_raises_not_implemented(self):
        wf = BulkImportWorkflow()
        with pytest.raises(NotImplementedError, match="Temporal"):
            await wf.run("job-id", "tenant-id")


class TestVerifyEmailSenderDomainWorkflow:
    @pytest.mark.asyncio
    async def test_raises_not_implemented(self):
        wf = VerifyEmailSenderDomainWorkflow()
        with pytest.raises(NotImplementedError, match="Temporal"):
            await wf.run("domain-id", "tenant-id")


class TestDNSHeartbeatWorkflow:
    @pytest.mark.asyncio
    async def test_raises_not_implemented(self):
        wf = DNSHeartbeatWorkflow()
        with pytest.raises(NotImplementedError, match="Temporal"):
            await wf.run()
