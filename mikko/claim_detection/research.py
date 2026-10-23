"""Dataset auditing and development-only threshold selection from saved scores.

Usage: python -m claim_detection.research audit DATA.jsonl --output audit.json
       python -m claim_detection.research sweep RUN_DIRECTORY --output sweep.json
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from .core import probability
from .evaluation import read_rows, validate_splits, metrics, digest


def audit(rows):
    validate_splits(rows)
    summary = {}
    warnings = []
    for split in ("train", "dev", "test"):
        selected = [r for r in rows if r["split"] == split]
        labeled = [r for r in selected if type(r.get("label")) is bool]
        positive = sum(r["label"] for r in labeled)
        summary[split] = {
            "segments": len(selected), "videos": len({r["video_id"] for r in selected}),
            "labeled": len(labeled), "positive": positive,
            "negative": len(labeled)-positive,
            "unlabeled_or_invalid": len(selected)-len(labeled),
            "categories": dict(Counter(str(r.get("category", "unspecified")) for r in selected)),
        }
        if not selected:
            warnings.append(f"{split}: empty split")
        elif positive == 0 or positive == len(labeled):
            warnings.append(f"{split}: lacks labeled examples from both classes")
        if len(labeled) != len(selected):
            warnings.append(f"{split}: incomplete or invalid labels")
    # Repeated text can leak even when video IDs differ; report for human review.
    texts = {}
    for row in rows:
        key = " ".join(row["text"].lower().split())
        texts.setdefault(key, set()).add(row["split"])
    duplicates = sum(len(splits) > 1 for splits in texts.values())
    if duplicates:
        warnings.append(f"{duplicates} normalized texts occur across splits; review duplicates")
    synthetic = sum(r.get("synthetic") is True for r in rows)
    if synthetic:
        warnings.append(f"{synthetic} synthetic examples: not human annotation evidence")
    return {"splits": summary, "synthetic_examples": synthetic, "warnings": warnings,
            "note": "Boolean labels are format-valid, not proof of human review."}


def sweep(run_directory):
    directory = Path(run_directory)
    report = json.loads((directory / "metrics.json").read_text())
    if report["run"]["split"] != "dev":
        raise ValueError("threshold selection is allowed only on development runs")
    predictions = read_rows(directory / "predictions.jsonl")
    if any(r.get("split") != "dev" for r in predictions):
        raise ValueError("prediction rows must explicitly identify the dev split; regenerate old runs")
    gold = [r["gold"] for r in predictions]
    scores = [probability(r["confidence"]) for r in predictions]
    table = [{"threshold": i/20, **metrics(gold, [s >= i/20 for s in scores])}
             for i in range(21)]
    # Predeclared tie-breaker: F1, then precision, then higher threshold.
    selected = max(table, key=lambda row: (row["f1"], row["precision"], row["threshold"]))
    return {"source_run": report["run"],
            "predictions_sha256": digest((directory / "predictions.jsonl").read_bytes()),
            "selection_rule": "max dev F1; ties: precision, then higher threshold",
            "selected": selected, "thresholds": table,
            "note": "Exploratory development selection; not held-out performance."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["audit", "sweep"])
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("choose a new output path; existing results are preserved")
        result = audit(read_rows(args.input)) if args.command == "audit" else sweep(args.input)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps(result, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
