"""Evaluation with video-level separation and auditable prediction rows."""
import hashlib
import json
import random
from .core import Segment, detect


def read_rows(path):
    rows = []
    seen = set()
    with open(path) as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("each JSONL row must be an object")
                segment = Segment.from_dict(row)
                if segment.segment_id in seen:
                    raise ValueError("duplicate segment_id")
                seen.add(segment.segment_id)
                rows.append(row)
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
    if not rows:
        raise ValueError("dataset is empty")
    return rows


def write_jsonl(path, rows):
    with open(path, "w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def validate_splits(rows):
    by_video = {}
    for row in rows:
        split = row.get("split")
        if split not in ("train", "dev", "test"):
            raise ValueError("every evaluated row needs train/dev/test split")
        video = row["video_id"]
        if video in by_video and by_video[video] != split:
            raise ValueError(f"video leakage across splits: {video}")
        by_video[video] = split


def assign_splits(rows, seed=4701):
    videos = sorted({r["video_id"] for r in rows})
    if len(videos) < 3:
        raise ValueError("need at least three videos for disjoint train/dev/test sets")
    random.Random(seed).shuffle(videos)
    n_test = max(1, round(len(videos) * 0.2))
    n_dev = max(1, round(len(videos) * 0.2))
    mapping = {v: "test" if i < n_test else "dev" if i < n_test+n_dev else "train"
               for i, v in enumerate(videos)}
    return [{**r, "split": mapping[r["video_id"]]} for r in rows]


def metrics(gold, predicted):
    if not gold or len(gold) != len(predicted):
        raise ValueError("expected nonempty equal-length label lists")
    if any(type(x) is not bool for x in [*gold, *predicted]):
        raise ValueError("labels must be JSON booleans")
    tp = sum(g and p for g, p in zip(gold, predicted))
    fp = sum(not g and p for g, p in zip(gold, predicted))
    fn = sum(g and not p for g, p in zip(gold, predicted))
    tn = len(gold)-tp-fp-fn
    precision = tp/(tp+fp) if tp+fp else 0.0
    recall = tp/(tp+fn) if tp+fn else 0.0
    return {"n": len(gold), "positive_support": sum(gold), "tp": tp, "fp": fp,
            "fn": fn, "tn": tn, "precision": precision, "recall": recall,
            "f1": 2*precision*recall/(precision+recall) if precision+recall else 0.0}


def evaluate(rows, detector, split, threshold):
    validate_splits(rows)
    selected = [r for r in rows if r["split"] == split]
    if not selected:
        raise ValueError(f"no examples for split {split}")
    if any(type(r.get("label")) is not bool for r in selected):
        raise ValueError("selected rows must have human-reviewed boolean labels")
    predictions = [{**detect(Segment.from_dict(r), detector, threshold),
                    "gold": r["label"], "split": r["split"],
                    "synthetic": r.get("synthetic", False),
                    "category": r.get("category", "unspecified")}
                   for r in selected]
    def summarize(items):
        return metrics([p["gold"] for p in items], [p["is_context_worthy"] for p in items])
    categories = sorted({p["category"] for p in predictions})
    return predictions, {"overall": summarize(predictions), "by_category": {
        c: summarize([p for p in predictions if p["category"] == c]) for c in categories}}


def digest(data):
    return hashlib.sha256(data).hexdigest()
