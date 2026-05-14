"""Unit tests for content workflows."""

from __future__ import annotations

import uuid
import pytest

from app.modules.content.workflows import ContentBriefGenWorkflow


class TestContentBriefGenWorkflow:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = ContentBriefGenWorkflow()
        with pytest.raises(NotImplementedError, match="Temporal"):
            await wf.run(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
