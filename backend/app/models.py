from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="preview")
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    staged_rows: Mapped[str] = mapped_column(Text, default="[]")
    errors: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_feedback_content_hash"),
        Index("ix_feedback_received_at", "received_at"),
        Index("ix_feedback_product", "product"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product: Mapped[str | None] = mapped_column(String(255), nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    classification: Mapped["Classification | None"] = relationship(
        back_populates="feedback", cascade="all, delete-orphan", uselist=False
    )


class Classification(Base):
    __tablename__ = "classifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("feedback.id", ondelete="CASCADE"), unique=True)
    predicted_sentiment: Mapped[str] = mapped_column(String(20))
    predicted_category: Mapped[str] = mapped_column(String(40))
    predicted_severity: Mapped[str] = mapped_column(String(20))
    predicted_summary: Mapped[str] = mapped_column(String(280))
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str] = mapped_column(Text)
    current_sentiment: Mapped[str] = mapped_column(String(20))
    current_category: Mapped[str] = mapped_column(String(40))
    current_severity: Mapped[str] = mapped_column(String(20))
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(30), default="rule")

    feedback: Mapped[Feedback] = relationship(back_populates="classification")


class IssueGroup(Base):
    __tablename__ = "issue_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(280))
    category: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class IssueMembership(Base):
    __tablename__ = "issue_memberships"
    __table_args__ = (UniqueConstraint("issue_id", "feedback_id", name="uq_issue_feedback"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issue_groups.id", ondelete="CASCADE"), index=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("feedback.id", ondelete="CASCADE"), index=True)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issue_groups.id", ondelete="CASCADE"), index=True)
    problem: Mapped[str] = mapped_column(Text)
    why_it_matters: Mapped[str] = mapped_column(Text)
    suggested_action: Mapped[str] = mapped_column(Text)
    expected_outcome: Mapped[str] = mapped_column(Text)
    evaluation_method: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CorrectionHistory(Base):
    __tablename__ = "correction_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("feedback.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(30))
    previous_value: Mapped[str] = mapped_column(String(280))
    corrected_value: Mapped[str] = mapped_column(String(280))
    corrected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
