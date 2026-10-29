from collections import defaultdict
from datetime import datetime, timezone
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Classification,
    Feedback,
    IssueGroup,
    IssueMembership,
    Recommendation,
)

SEVERITY_VALUE = {"low": 1 / 3, "medium": 2 / 3, "high": 1.0}
def cluster_feedback(items: list[Feedback], threshold: float | None = None) -> list[list[Feedback]]:
    if threshold is None:
        threshold = get_settings().clustering_threshold
    buckets: dict[str, list[Feedback]] = defaultdict(list)
    for item in items:
        if item.classification:
            buckets[item.classification.current_category].append(item)

    clusters: list[list[Feedback]] = []
    for members in buckets.values():
        if len(members) < 2:
            clusters.extend([[member] for member in members])
            continue
        corpus = [member.text.casefold() for member in members]
        try:
            matrix = TfidfVectorizer(stop_words="english", ngram_range=(1, 2)).fit_transform(corpus)
            similarities = cosine_similarity(matrix)
        except ValueError:
            clusters.extend([[member] for member in members])
            continue
        parent = list(range(len(members)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        for left in range(len(members)):
            for right in range(left + 1, len(members)):
                if similarities[left, right] >= threshold:
                    parent[find(right)] = find(left)
        groups: dict[int, list[Feedback]] = defaultdict(list)
        for index, member in enumerate(members):
            groups[find(index)].append(member)
        clusters.extend(groups.values())
    return clusters


def rebuild_issue_groups(db: Session, items: list[Feedback]) -> None:
    db.execute(delete(Recommendation))
    db.execute(delete(IssueMembership))
    db.execute(delete(IssueGroup))
    clusters = cluster_feedback(items)
    for cluster in clusters:
        category = cluster[0].classification.current_category
        keywords = re.findall(r"[a-zA-Z]{4,}", " ".join(item.text for item in cluster).casefold())
        title = f"{category.title()}: {', '.join(dict.fromkeys(keywords[:3]))}" if keywords else f"{category.title()} feedback"
        issue = IssueGroup(title=title[:280], category=category)
        db.add(issue)
        db.flush()
        for item in cluster:
            db.add(IssueMembership(issue_id=issue.id, feedback_id=item.id))
    db.flush()
    feedback_by_id = {item.id: item for item in items}
    for ranking in issue_rankings(db):
        if ranking["priority_level"] != "high":
            continue
        category = ranking["category"]
        evidence = [
            f'#{item_id}: "{feedback_by_id[item_id].text[:180]}"'
            for item_id in ranking["feedback_ids"][:3]
        ]
        db.add(
            Recommendation(
                issue_id=ranking["id"],
                problem=f"{ranking['count']} feedback item(s) form a high-priority {category} issue.",
                why_it_matters="Supporting customer evidence: " + " | ".join(evidence),
                suggested_action=f"Review the supporting feedback and investigate the {category} workflow before choosing a fix.",
                expected_outcome="Hypothesis: addressing this issue may reduce similar complaints; measure before and after to verify.",
                evaluation_method="Track the count and share of matching feedback over the next 30 days.",
            )
        )


def issue_rankings(db: Session, feedback_ids: set[int] | None = None) -> list[dict]:
    rows = db.execute(
        select(IssueGroup, Feedback, Classification)
        .join(IssueMembership, IssueMembership.issue_id == IssueGroup.id)
        .join(Feedback, Feedback.id == IssueMembership.feedback_id)
        .join(Classification, Classification.feedback_id == Feedback.id)
        .order_by(IssueGroup.id)
    ).all()
    groups: dict[int, dict] = {}
    for issue, feedback, classification in rows:
        if feedback_ids is not None and feedback.id not in feedback_ids:
            continue
        group = groups.setdefault(issue.id, {"issue": issue, "items": []})
        group["items"].append((feedback, classification))
    now = datetime.now(timezone.utc)
    settings = get_settings()
    weights = {
        "frequency": settings.priority_weight_frequency,
        "severity": settings.priority_weight_severity,
        "recency": settings.priority_weight_recency,
        "negative_sentiment": settings.priority_weight_negative_sentiment,
        "rating": settings.priority_weight_rating,
    }
    weight_total = sum(weights.values())
    if weight_total <= 0:
        raise ValueError("At least one priority score weight must be greater than zero")
    weights = {key: value / weight_total for key, value in weights.items()}
    frequencies = [len(group["items"]) for group in groups.values()]
    max_frequency = max(frequencies, default=1)
    ranked = []
    for group in groups.values():
        issue, pairs = group["issue"], group["items"]
        count = len(pairs)
        severity = sum(SEVERITY_VALUE[c.current_severity] for _, c in pairs) / count
        negative = sum(c.current_sentiment == "negative" for _, c in pairs) / count
        dated = [f.received_at for f, _ in pairs if f.received_at]
        if dated:
            ages = [max(0.0, (now - (date if date.tzinfo else date.replace(tzinfo=timezone.utc))).days) for date in dated]
            recency = sum(1 / (1 + age / 30) for age in ages) / len(ages)
        else:
            recency = 0.5
        rated = [f.rating for f, _ in pairs if f.rating is not None]
        rating = sum((5 - value) / 4 for value in rated) / len(rated) if rated else 0.5
        components = {
            "frequency": count / max_frequency,
            "severity": severity,
            "recency": recency,
            "negative_sentiment": negative,
            "rating": rating,
        }
        contributions = {key: components[key] * weights[key] for key in weights}
        score = sum(contributions.values())
        rec = db.scalar(select(Recommendation).where(Recommendation.issue_id == issue.id))
        reasons = [
            f"{count} related feedback item(s)",
            f"{negative:.0%} classified as negative",
            f"Average severity contribution {severity:.2f} on a 0-1 scale",
        ]
        ranked.append({
            "id": issue.id,
            "title": issue.title,
            "category": issue.category,
            "count": count,
            "priority_score": round(score * 100, 1),
            "priority_level": "high" if score >= 0.70 else "medium" if score >= 0.45 else "low",
            "components": components,
            "contributions": contributions,
            "weights": weights,
            "reasons": reasons,
            "feedback_ids": [feedback.id for feedback, _ in pairs],
            "recommendation": {
                "problem": rec.problem,
                "why_it_matters": rec.why_it_matters,
                "suggested_action": rec.suggested_action,
                "expected_outcome": rec.expected_outcome,
                "evaluation_method": rec.evaluation_method,
            } if rec else None,
        })
    return sorted(ranked, key=lambda issue: issue["priority_score"], reverse=True)
