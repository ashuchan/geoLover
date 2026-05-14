"""Content generation workflow stub (requires Temporal for full implementation)."""

from __future__ import annotations

import uuid


class ContentBriefGenWorkflow:
    """Temporal workflow for generating content briefs from an audit run.

    Full implementation requires Temporal; this stub raises NotImplementedError.
    """

    async def run(
        self,
        audit_run_id: uuid.UUID,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> None:
        raise NotImplementedError("ContentBriefGenWorkflow requires Temporal")
