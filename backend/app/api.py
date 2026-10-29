import csv
import io
import json
import logging
from datetime import date, datetime, time, timezone
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.db import get_db
from app.models import (
    Classification,
    CorrectionHistory,
    Feedback,
    ImportBatch,
    IssueGroup,
    IssueMembership,
    Recommendation,
)
from app.schemas import ConfirmImportIn, CorrectionIn
from app.services.classifier import classify_feedback
from app.services.imports import parse_preview
from app.services.prioritization import issue_rankings, rebuild_issue_groups

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")
DbSession = Annotated[Session, Depends(get_db)]


def feedback_to_dict(feedback: Feedback) -> dict:
    classification = feedback.classification
    return {
        "id": feedback.id,
        "text": feedback.text,
        "received_at": feedback.received_at,
        "rating": feedback.rating,
        "customer_id": feedback.customer_id,
        "product": feedback.product,
        "sentiment": classification.current_sentiment,
        "category": classification.current_category,
        "severity": classification.current_severity,
        "predicted_sentiment": classification.predicted_sentiment,
        "predicted_category": classification.predicted_category,
        "predicted_severity": classification.predicted_severity,
        "summary": classification.predicted_summary,
        "confidence": classification.confidence,
        "evidence": classification.evidence,
        "corrected_at": classification.corrected_at,
    }


def filtered_feedback_query(
    db: Session,
    start_date: date | None,
    end_date: date | None,
    category: str | None,
    sentiment: str | None,
    severity: str | None,
    product: str | None,
    search: str | None,
):
    query = select(Feedback).join(Classification).options(joinedload(Feedback.classification))
    if start_date:
        query = query.where(Feedback.received_at >= datetime.combine(start_date, time.min, tzinfo=timezone.utc))
    if end_date:
        query = query.where(
            Feedback.received_at < datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
        )
    if category:
        query = query.where(Classification.current_category == category)
    if sentiment:
        query = query.where(Classification.current_sentiment == sentiment)
    if severity:
        query = query.where(Classification.current_severity == severity)
    if product:
        query = query.where(Feedback.product == product)
    if search:
        escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Feedback.text.ilike(f"%{escaped_search}%", escape="\\"))
    return query


def filter_parameters(
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    severity: str | None = None,
    product: str | None = None,
    search: str | None = None,
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    return start_date, end_date, category, sentiment, severity, product, search


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/imports/sample.csv")
def sample_csv():
    return Response(
        "feedback,date,rating,customer_id,product\n"
        '"Delivery arrived three days late",2026-10-10,2,cust-001,Online store\n'
        '"Support resolved my billing issue quickly",2026-10-11,5,cust-002,Online store\n',
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sample_feedback.csv"'},
    )


@router.post("/imports/preview")
async def preview_import(
    db: DbSession,
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str | None, Form()] = None,
):
    if not file.filename or not file.filename.casefold().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Upload a .csv file")
    content = await file.read(get_settings().upload_max_bytes + 1)
    if len(content) > get_settings().upload_max_bytes:
        limit_mb = get_settings().upload_max_bytes / (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"CSV exceeds the configured {limit_mb:g} MB upload limit")
    try:
        batch, preview = parse_preview(db, file.filename, content, mapping)
    except (ValueError, json.JSONDecodeError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    errors = json.loads(batch.errors)
    return {
        "batch_id": batch.id,
        "filename": batch.filename,
        "total_rows": batch.total_rows,
        "valid_rows": len(json.loads(batch.staged_rows)),
        "rejected_rows": batch.rejected_rows,
        "duplicate_rows": batch.duplicate_rows,
        "preview": preview,
        "errors": errors[:25],
    }


@router.post("/imports/confirm")
def confirm_import(payload: ConfirmImportIn, db: DbSession):
    batch_id = payload.batch_id
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import preview not found")
    if batch.status != "preview":
        raise HTTPException(status_code=409, detail="This import preview has already been confirmed")
    imported = 0
    rows = json.loads(batch.staged_rows)
    try:
        for row in rows:
            exists = db.scalar(select(Feedback.id).where(Feedback.content_hash == row["content_hash"]))
            if exists:
                batch.duplicate_rows += 1
                continue
            received_at = datetime.fromisoformat(row["received_at"]) if row.get("received_at") else None
            feedback = Feedback(
                text=row["text"],
                content_hash=row["content_hash"],
                received_at=received_at,
                rating=row.get("rating"),
                customer_id=row.get("customer_id"),
                product=row.get("product"),
                import_batch_id=batch.id,
            )
            result, provider = classify_feedback(row["text"])
            feedback.classification = Classification(
                predicted_sentiment=result.sentiment,
                predicted_category=result.category,
                predicted_severity=result.severity,
                predicted_summary=result.summary,
                confidence=result.confidence,
                evidence=result.evidence,
                current_sentiment=result.sentiment,
                current_category=result.category,
                current_severity=result.severity,
                provider=provider,
            )
            db.add(feedback)
            imported += 1
        batch.status = "complete"
        batch.imported_rows = imported
        all_feedback = db.scalars(select(Feedback).options(joinedload(Feedback.classification))).unique().all()
        db.flush()
        rebuild_issue_groups(db, all_feedback)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Import confirmation failed for batch %s (%s)", batch_id, type(exc).__name__)
        raise HTTPException(status_code=500, detail="Import could not be completed; no rows were committed")
    return {
        "batch_id": batch.id,
        "status": batch.status,
        "imported_rows": batch.imported_rows,
        "rejected_rows": batch.rejected_rows,
        "duplicate_rows": batch.duplicate_rows,
    }


@router.get("/imports")
def import_history(db: DbSession):
    batches = db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc())).all()
    return [
        {
            "id": item.id,
            "filename": item.filename,
            "status": item.status,
            "total_rows": item.total_rows,
            "imported_rows": item.imported_rows,
            "rejected_rows": item.rejected_rows,
            "duplicate_rows": item.duplicate_rows,
            "created_at": item.created_at,
        }
        for item in batches
    ]


@router.get("/feedback")
def list_feedback(
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    severity: str | None = None,
    product: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    filters = filter_parameters(start_date, end_date, category, sentiment, severity, product, search)
    query = filtered_feedback_query(db, *filters)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(Feedback.received_at.desc().nullslast(), Feedback.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique().all()
    return {
        "items": [feedback_to_dict(item) for item in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/feedback/{feedback_id}")
def get_feedback(feedback_id: int, db: DbSession):
    feedback = db.scalar(
        select(Feedback).options(joinedload(Feedback.classification)).where(Feedback.id == feedback_id)
    )
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return feedback_to_dict(feedback)


@router.patch("/feedback/{feedback_id}")
def correct_feedback(feedback_id: int, payload: CorrectionIn, db: DbSession):
    classification = db.scalar(
        select(Classification).where(Classification.feedback_id == feedback_id)
    )
    if not classification:
        raise HTTPException(status_code=404, detail="Feedback not found")
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one classification field must be provided")
    for field, value in changes.items():
        db.add(
            CorrectionHistory(
                feedback_id=feedback_id,
                field=field,
                previous_value=getattr(classification, f"current_{field}"),
                corrected_value=value,
            )
        )
        setattr(classification, f"current_{field}", value)
    classification.corrected_at = datetime.now(timezone.utc)
    feedback_items = db.scalars(
        select(Feedback).options(joinedload(Feedback.classification))
    ).unique().all()
    db.flush()
    rebuild_issue_groups(db, feedback_items)
    db.commit()
    return get_feedback(feedback_id, db)


@router.get("/dashboard")
def dashboard(
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    severity: str | None = None,
    product: str | None = None,
    search: str | None = None,
):
    filters = filter_parameters(start_date, end_date, category, sentiment, severity, product, search)
    items = db.scalars(filtered_feedback_query(db, *filters)).unique().all()
    sentiment_counts = {key: 0 for key in ("positive", "neutral", "negative")}
    category_counts: dict[str, int] = {}
    volume: dict[str, int] = {}
    ratings: dict[str, list[float]] = {}
    for item in items:
        result = item.classification
        sentiment_counts[result.current_sentiment] += 1
        category_counts[result.current_category] = category_counts.get(result.current_category, 0) + 1
        if item.received_at:
            key = item.received_at.date().isoformat()
            volume[key] = volume.get(key, 0) + 1
            if item.rating is not None:
                ratings.setdefault(key, []).append(item.rating)
    priorities = issue_rankings(db, {item.id for item in items})
    return {
        "total_feedback": len(items),
        "sentiment_counts": sentiment_counts,
        "category_counts": category_counts,
        "sentiment_distribution": [
            {"sentiment": key, "count": value} for key, value in sentiment_counts.items()
        ],
        "feedback_over_time": [{"date": key, "count": value} for key, value in sorted(volume.items())],
        "rating_trends": [
            {"date": key, "average_rating": round(sum(values) / len(values), 2)}
            for key, values in sorted(ratings.items())
        ],
        "priority_issues": priorities[:5],
        "issue_group_count": len(priorities),
        "recommendation_count": sum(issue["recommendation"] is not None for issue in priorities),
    }


@router.get("/issues")
def list_issues(
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    severity: str | None = None,
    product: str | None = None,
    search: str | None = None,
):
    filters = filter_parameters(start_date, end_date, category, sentiment, severity, product, search)
    items = db.scalars(filtered_feedback_query(db, *filters)).unique().all()
    return issue_rankings(db, {item.id for item in items})


@router.get("/issues/{issue_id}")
def issue_detail(
    issue_id: int,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    severity: str | None = None,
    product: str | None = None,
    search: str | None = None,
):
    issue = db.get(IssueGroup, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    filters = filter_parameters(start_date, end_date, category, sentiment, severity, product, search)
    matching_items = db.scalars(filtered_feedback_query(db, *filters)).unique().all()
    matching_ids = {item.id for item in matching_items}
    ranking = next(
        (item for item in issue_rankings(db, matching_ids) if item["id"] == issue_id),
        None,
    )
    if not ranking:
        raise HTTPException(status_code=404, detail="Issue has no feedback")
    feedback_items = db.scalars(
        select(Feedback)
        .join(IssueMembership, IssueMembership.feedback_id == Feedback.id)
        .options(joinedload(Feedback.classification))
        .where(IssueMembership.issue_id == issue_id, Feedback.id.in_(matching_ids))
        .order_by(Feedback.received_at)
    ).unique().all()
    ranking["feedback"] = [
        feedback_to_dict(item)
        for item in feedback_items
    ]
    volume: dict[str, int] = {}
    ratings: dict[str, list[float]] = {}
    for item in feedback_items:
        if item.received_at:
            day = item.received_at.date().isoformat()
            volume[day] = volume.get(day, 0) + 1
            if item.rating is not None:
                ratings.setdefault(day, []).append(item.rating)
    ranking["feedback_over_time"] = [
        {"date": day, "count": count} for day, count in sorted(volume.items())
    ]
    ranking["rating_trends"] = [
        {"date": day, "average_rating": round(sum(values) / len(values), 2)}
        for day, values in sorted(ratings.items())
    ]
    return ranking


@router.get("/recommendations")
def recommendations(
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    severity: str | None = None,
    product: str | None = None,
    search: str | None = None,
):
    filters = filter_parameters(start_date, end_date, category, sentiment, severity, product, search)
    items = db.scalars(filtered_feedback_query(db, *filters)).unique().all()
    feedback_by_id = {item.id: item.text for item in items}
    issue_feedback = {
        item["id"]: item["feedback_ids"]
        for item in issue_rankings(db, {feedback.id for feedback in items})
    }
    rows = db.execute(select(Recommendation, IssueGroup).join(IssueGroup)).all()
    return [
        {
            "id": recommendation.id,
            "issue_id": issue.id,
            "issue_title": issue.title,
            "category": issue.category,
            "problem": f"{len(issue_feedback[issue.id])} matching feedback item(s) in {issue.category}.",
            "why_it_matters": "Supporting feedback: " + " | ".join(
                f'"{feedback_by_id[feedback_id][:180]}"'
                for feedback_id in issue_feedback[issue.id][:3]
                if feedback_id in feedback_by_id
            ),
            "suggested_action": recommendation.suggested_action,
            "expected_outcome": recommendation.expected_outcome,
            "evaluation_method": recommendation.evaluation_method,
            "feedback_ids": issue_feedback.get(issue.id, []),
        }
        for recommendation, issue in rows
        if issue.id in issue_feedback
    ]


@router.get("/exports/feedback.csv")
def export_feedback(
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    severity: str | None = None,
    product: str | None = None,
    search: str | None = None,
):
    filters = filter_parameters(start_date, end_date, category, sentiment, severity, product, search)
    items = db.scalars(filtered_feedback_query(db, *filters)).unique().all()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "feedback", "date", "rating", "customer_id", "product", "sentiment", "category", "severity", "summary"])
    for item in items:
        writer.writerow([
            item.id, item.text, item.received_at.isoformat() if item.received_at else "",
            item.rating if item.rating is not None else "", item.customer_id or "", item.product or "",
            item.classification.current_sentiment, item.classification.current_category,
            item.classification.current_severity, item.classification.predicted_summary,
        ])
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="feedback_export.csv"'},
    )


@router.get("/exports/issues.csv")
def export_issues(
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    severity: str | None = None,
    product: str | None = None,
    search: str | None = None,
):
    filters = filter_parameters(start_date, end_date, category, sentiment, severity, product, search)
    items = db.scalars(filtered_feedback_query(db, *filters)).unique().all()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["issue", "category", "feedback_count", "priority_score", "priority_level", "suggested_action", "expected_outcome"])
    for issue in issue_rankings(db, {item.id for item in items}):
        recommendation = issue["recommendation"] or {}
        writer.writerow([
            issue["title"], issue["category"], issue["count"], issue["priority_score"],
            issue["priority_level"], recommendation.get("suggested_action", ""),
            recommendation.get("expected_outcome", ""),
        ])
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="issue_priorities.csv"'},
    )
