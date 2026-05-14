"""Temporal workflow stubs for Whitelabel & Agency Portal module."""

from __future__ import annotations


class VerifyDomainWorkflow:
    """Temporal workflow stub for domain DNS verification."""

    async def run(self, mapping_id: str, tenant_id: str) -> None:
        raise NotImplementedError("VerifyDomainWorkflow requires Temporal")


class ProvisionSSLWorkflow:
    """Temporal workflow stub for SSL certificate provisioning."""

    async def run(self, mapping_id: str) -> None:
        raise NotImplementedError("ProvisionSSLWorkflow requires Temporal")


class BulkImportWorkflow:
    """Temporal workflow stub for bulk business CSV import."""

    async def run(self, job_id: str, tenant_id: str) -> None:
        raise NotImplementedError("BulkImportWorkflow requires Temporal")


class VerifyEmailSenderDomainWorkflow:
    """Temporal workflow stub for email sender domain verification."""

    async def run(self, domain_id: str, tenant_id: str) -> None:
        raise NotImplementedError("VerifyEmailSenderDomainWorkflow requires Temporal")


class DNSHeartbeatWorkflow:
    """Temporal workflow stub for periodic DNS verification heartbeat."""

    async def run(self) -> None:
        raise NotImplementedError("DNSHeartbeatWorkflow requires Temporal")
