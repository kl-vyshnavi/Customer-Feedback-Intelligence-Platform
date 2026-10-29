from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Sentiment = Literal["positive", "neutral", "negative"]
Category = Literal[
    "pricing", "product quality", "delivery", "customer support", "usability", "billing", "other"
]
Severity = Literal["low", "medium", "high"]


class ClassificationResult(BaseModel):
    sentiment: Sentiment
    category: Category
    severity: Severity
    summary: str = Field(min_length=1, max_length=280)
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(min_length=1)


class FeedbackOut(BaseModel):
    id: int
    text: str
    received_at: datetime | None
    rating: float | None
    customer_id: str | None
    product: str | None
    sentiment: Sentiment
    category: Category
    severity: Severity
    summary: str
    confidence: float
    evidence: str
    corrected_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class CorrectionIn(BaseModel):
    sentiment: Sentiment | None = None
    category: Category | None = None
    severity: Severity | None = None


class PreviewOut(BaseModel):
    batch_id: int
    filename: str
    total_rows: int
    valid_rows: int
    rejected_rows: int
    duplicate_rows: int
    preview: list[dict]
    errors: list[dict]


class ConfirmImportIn(BaseModel):
    batch_id: int


class PriorityComponent(BaseModel):
    frequency: float
    severity: float
    recency: float
    negative_sentiment: float
    rating: float


class IssueOut(BaseModel):
    id: int
    title: str
    category: str
    count: int
    priority_score: float
    priority_level: str
    components: PriorityComponent
    reasons: list[str]
    feedback_ids: list[int]
    recommendation: dict | None = None
