import csv
from pathlib import Path

from sklearn.metrics import accuracy_score, precision_recall_fscore_support

from app.services.classifier import rule_classify

LABEL_FIELDS = ("sentiment", "category", "severity")
DATASET = Path(__file__).with_name("labels.csv")


def main() -> None:
    with DATASET.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    for field in LABEL_FIELDS:
        expected = [row[f"expected_{field}"] for row in rows]
        predicted = [getattr(rule_classify(row["feedback"]), field) for row in rows]
        precision, recall, f1, _ = precision_recall_fscore_support(
            expected,
            predicted,
            average="macro",
            zero_division=0,
        )
        print(
            f"{field}: n={len(rows)}, accuracy={accuracy_score(expected, predicted):.3f}, "
            f"macro_precision={precision:.3f}, macro_recall={recall:.3f}, macro_f1={f1:.3f}"
        )


if __name__ == "__main__":
    main()
