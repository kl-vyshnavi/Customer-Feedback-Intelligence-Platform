import csv
import io

from app.schemas import ClassificationResult
from pydantic import ValidationError


def preview(client, content: str, filename: str = "feedback.csv"):
    return client.post(
        "/api/v1/imports/preview",
        files={"file": (filename, content.encode(), "text/csv")},
    )


def confirm(client, batch_id: int):
    return client.post("/api/v1/imports/confirm", json={"batch_id": batch_id})


def import_rows(client, content: str):
    result = preview(client, content)
    assert result.status_code == 200
    imported = confirm(client, result.json()["batch_id"])
    assert imported.status_code == 200
    return imported.json()


def test_preview_validates_rows_and_reports_duplicates(client):
    result = preview(
        client,
        "review,date,rating,product\n"
        '"Delivery arrived three days late",2026-10-10,2,Store\n'
        '"Delivery arrived three days late",2026-10-10,2,Store\n'
        '"",2026-10-10,3,Store\n'
        '"Broken item",2026-10-10,8,Store\n',
    )
    assert result.status_code == 200
    body = result.json()
    assert body["total_rows"] == 4
    assert body["valid_rows"] == 1
    assert body["duplicate_rows"] == 1
    assert body["rejected_rows"] == 2
    assert len(body["errors"]) == 2


def test_column_mapping_file_type_and_empty_file_validation(client):
    no_text = preview(client, "topic,body\nx,hello", "notes.csv")
    assert no_text.status_code == 422
    mapped = client.post(
        "/api/v1/imports/preview",
        data={"mapping": '{"text":"body","product":"topic"}'},
        files={"file": ("notes.csv", b"topic,body\nstore,Great service", "text/csv")},
    )
    assert mapped.status_code == 200
    assert mapped.json()["preview"][0]["product"] == "store"
    wrong_type = preview(client, "text\nhello", "reviews.txt")
    assert wrong_type.status_code == 415
    empty = preview(client, "")
    assert empty.status_code == 422


def test_import_confirmation_is_idempotent_and_stores_classification(client):
    imported = import_rows(
        client,
        "feedback,date,rating\n"
        '"Delivery arrived three days late",2026-10-10,2\n'
        '"Support was very helpful",2026-10-11,5\n',
    )
    assert imported["imported_rows"] == 2
    assert imported["duplicate_rows"] == 0
    assert client.get("/api/v1/feedback").json()["total"] == 2
    repeated = confirm(client, imported["batch_id"])
    assert repeated.status_code == 409
    feedback = client.get("/api/v1/feedback").json()["items"][0]
    assert feedback["category"] in {"delivery", "customer support"}
    assert feedback["evidence"] in feedback["text"]
    assert feedback["predicted_category"] == feedback["category"]


def test_existing_feedback_is_reported_as_duplicate(client):
    source = "feedback\nGreat product quality\n"
    import_rows(client, source)
    second_preview = preview(client, source).json()
    assert second_preview["valid_rows"] == 0
    assert second_preview["duplicate_rows"] == 1
    result = confirm(client, second_preview["batch_id"]).json()
    assert result["imported_rows"] == 0
    assert client.get("/api/v1/feedback").json()["total"] == 1


def test_classification_schema_rejects_invalid_values():
    try:
        ClassificationResult.model_validate({
            "sentiment": "very bad",
            "category": "delivery",
            "severity": "high",
            "summary": "Late delivery",
            "confidence": 1.2,
            "evidence": "The package was late",
        })
    except ValidationError:
        pass
    else:
        raise AssertionError("Invalid classification data should fail Pydantic validation")


def test_feedback_filters_pagination_corrections_and_exports(client):
    import_rows(
        client,
        "feedback,date,rating,product\n"
        '"Delivery was late",2026-10-10,2,Store\n'
        '"The delivery was late again",2026-10-12,1,Store\n'
        '"The support team was helpful",2026-10-15,5,Service\n',
    )
    filtered = client.get(
        "/api/v1/feedback",
        params={"start_date": "2026-10-10", "end_date": "2026-10-12", "category": "delivery", "page_size": 1},
    ).json()
    assert filtered["total"] == 2
    assert len(filtered["items"]) == 1
    assert filtered["pages"] == 2
    dashboard = client.get(
        "/api/v1/dashboard",
        params={"start_date": "2026-10-10", "end_date": "2026-10-12", "category": "delivery"},
    ).json()
    assert dashboard["total_feedback"] == 2
    assert dashboard["category_counts"] == {"delivery": 2}
    assert client.get("/api/v1/feedback", params={"start_date": "2026-10-20", "end_date": "2026-10-10"}).status_code == 422
    feedback_id = filtered["items"][0]["id"]
    corrected = client.patch(f"/api/v1/feedback/{feedback_id}", json={"severity": "high"})
    assert corrected.status_code == 200
    assert corrected.json()["severity"] == "high"
    assert corrected.json()["predicted_severity"] != "high"
    assert corrected.json()["corrected_at"] is not None
    exported = client.get("/api/v1/exports/feedback.csv", params={"product": "Store"})
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == 2
    assert all(row["product"] == "Store" for row in rows)
    issue_export = client.get("/api/v1/exports/issues.csv", params={"product": "Service"})
    assert len(list(csv.DictReader(io.StringIO(issue_export.text)))) == 1


def test_priority_groups_and_evidence_linked_recommendations(client):
    import_rows(
        client,
        "feedback,rating\n"
        '"My delivery was late and the package arrived damaged",1\n'
        '"The package delivery arrived late and damaged",1\n'
        '"Delivery was very late and the box was damaged",2\n',
    )
    issues = client.get("/api/v1/issues").json()
    assert issues
    assert issues[0]["count"] == 3
    assert 0 <= issues[0]["priority_score"] <= 100
    assert issues[0]["priority_level"] in {"low", "medium", "high"}
    if issues[0]["recommendation"]:
        recommendations = client.get("/api/v1/recommendations").json()
        assert recommendations[0]["feedback_ids"]
        assert "Hypothesis" in recommendations[0]["expected_outcome"]


def test_ai_provider_failure_uses_rule_fallback(monkeypatch):
    import sys
    from types import SimpleNamespace

    from app.core.config import get_settings
    from app.services import classifier

    class BrokenClient:
        def __init__(self, **_kwargs):
            raise TimeoutError("provider unavailable")

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=BrokenClient))
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()
    result, provider = classifier.classify_feedback("My delivery was late")
    assert provider == "rule"
    assert result.category == "delivery"
