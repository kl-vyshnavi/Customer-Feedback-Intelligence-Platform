import csv
import hashlib
import io
import json
import logging
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Feedback, ImportBatch

logger = logging.getLogger(__name__)
FIELDS = ("text", "date", "rating", "customer_id", "product")
ALIASES = {
    "text": ("text", "feedback", "review", "comment", "message", "content"),
    "date": ("date", "created_at", "timestamp", "received_at"),
    "rating": ("rating", "stars", "score"),
    "customer_id": ("customer_id", "customer", "user_id"),
    "product": ("product", "service", "item", "product_name"),
}


def content_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.casefold().split()).encode("utf-8")).hexdigest()


def parse_preview(
    db: Session,
    filename: str,
    content: bytes,
    mapping_json: str | None,
) -> tuple[ImportBatch, list[dict]]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            decoded = content.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV encoding is not supported") from exc

    try:
        reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
        headers = [header.strip() for header in (reader.fieldnames or []) if header]
        if not headers:
            raise ValueError("CSV must include a header row")
        if len(set(headers)) != len(headers):
            raise ValueError("CSV header names must be unique")
        reader.fieldnames = headers
        source_mapping = {field: None for field in FIELDS}
        if mapping_json:
            mapping = json.loads(mapping_json)
            if not isinstance(mapping, dict) or set(mapping) - set(FIELDS):
                raise ValueError("Column mapping must map supported fields to CSV column names")
            for target, source in mapping.items():
                if source and source not in headers:
                    raise ValueError(f"Mapped column '{source}' does not exist in this CSV")
                source_mapping[target] = source
        else:
            for header in headers:
                normalized = header.casefold().strip().replace(" ", "_")
                for target, aliases in ALIASES.items():
                    if normalized in aliases and source_mapping[target] is None:
                        source_mapping[target] = header
        text_column = source_mapping.get("text")
        if text_column not in headers:
            raise ValueError("A feedback text column is required; provide a column mapping")

        staged: list[dict] = []
        errors: list[dict] = []
        seen: set[str] = set()
        duplicate_count = 0
        existing_hashes = set(db.scalars(select(Feedback.content_hash)).all())
        total_rows = 0
        for line_number, row in enumerate(reader, start=2):
            total_rows += 1
            if None in row or None in row.values():
                errors.append({"row": line_number, "message": "Row has more values than the header"})
                continue
            text = (row.get(text_column) or "").strip()
            if not text:
                errors.append({"row": line_number, "message": "Feedback text is required"})
                continue
            if len(text) > 10000:
                errors.append({"row": line_number, "message": "Feedback text exceeds 10,000 characters"})
                continue
            digest = content_hash(text)
            if digest in seen or digest in existing_hashes:
                duplicate_count += 1
                continue
            normalized = {"text": text, "content_hash": digest}
            date_value = row.get(source_mapping.get("date", "")) if source_mapping.get("date") else None
            if date_value:
                try:
                    parsed_date = pd.to_datetime(date_value.strip(), errors="raise", utc=True)
                    if pd.isna(parsed_date):
                        raise ValueError("Date is empty")
                    normalized["received_at"] = parsed_date.to_pydatetime().isoformat()
                except (ValueError, TypeError, OverflowError):
                    errors.append({"row": line_number, "message": "Date must use an ISO-compatible format"})
                    continue
            rating_value = row.get(source_mapping.get("rating", "")) if source_mapping.get("rating") else None
            if rating_value and rating_value.strip():
                try:
                    rating = float(rating_value.strip())
                except ValueError:
                    errors.append({"row": line_number, "message": "Rating must be a number from 1 to 5"})
                    continue
                if not 1 <= rating <= 5:
                    errors.append({"row": line_number, "message": "Rating must be between 1 and 5"})
                    continue
                normalized["rating"] = rating
            for field in ("customer_id", "product"):
                source = source_mapping.get(field)
                normalized[field] = (row.get(source) or "").strip() or None if source else None
            seen.add(digest)
            staged.append(normalized)
    except csv.Error as exc:
        raise ValueError("CSV contains malformed rows") from exc

    batch = ImportBatch(
        filename=filename[:255],
        status="preview",
        total_rows=total_rows,
        rejected_rows=len(errors),
        duplicate_rows=duplicate_count,
        staged_rows=json.dumps(staged, ensure_ascii=False),
        errors=json.dumps(errors, ensure_ascii=False),
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch, staged[:5]
