"""SQLAlchemy ORM model for the Category reference taxonomy."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Category(Base):
    """Two-level category taxonomy (not tenant-owned; global reference data)."""

    __tablename__ = "categories"
    __table_args__ = (
        Index("ix_categories_slug", "slug", unique=True),
        Index("ix_categories_parent", "parent_category_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    parent_category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    default_keyword_suggestions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    # Populated in Phase 2 when QueryTemplates are created
    default_query_template_set_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    parent: Mapped[Optional["Category"]] = relationship(
        "Category",
        remote_side="Category.id",
        lazy="noload",
    )
    children: Mapped[list["Category"]] = relationship(
        "Category",
        back_populates="parent",
        lazy="noload",
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("default_keyword_suggestions", [])
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)
