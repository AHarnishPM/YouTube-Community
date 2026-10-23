"""Turn caption exports into deterministic, timestamp-preserving windows.

Input JSON: {video_id, category, captions: [{start, duration, text}, ...]}.
Also accepts end instead of duration. Does not fetch videos or infer missing times.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
from .core import Segment
from .evaluation import write_jsonl


def windows(document, target_seconds=20, max_seconds=40, max_gap=3):
    if not 0 < target_seconds <= max_seconds or max_gap < 0:
        raise ValueError("require 0 < target <= maximum and gap >= 0")
    video = document["video_id"]
    captions = document["captions"]
    if not captions:
        raise ValueError("no captions")
    normalized = []
    for index, row in enumerate(captions):
        end = row.get("end")
        if end is None:
            end = row["start"] + row["duration"]
        item = Segment(str(index), video, row["start"], end, row["text"])
        if normalized and item.start < normalized[-1].start:
            raise ValueError("captions must be ordered by start time")
        if item.end-item.start > max_seconds:
            raise ValueError("one caption exceeds maximum window duration; provide finer timestamps")
        normalized.append(item)
    result, pending = [], []

    def emit():
        start, end = pending[0].start, max(c.end for c in pending)
        text = " ".join(c.text.strip() for c in pending)
        identity = json.dumps([video, start, end, text], ensure_ascii=False)
        identifier = hashlib.sha256(identity.encode()).hexdigest()[:20]
        value = asdict(Segment(f"{video}:w1:{identifier}", video, start, end, text))
        value.update(category=document.get("category", "unspecified"),
                     segmentation_version="caption-windows-v1",
                     source_caption_ids=[c.segment_id for c in pending])
        for key in ("source_url", "caption_source", "language", "synthetic"):
            if key in document:
                value[key] = document[key]
        result.append(value)
        pending.clear()

    for item in normalized:
        if pending:
            span = max(item.end, *(c.end for c in pending))-pending[0].start
            gap = item.start-max(c.end for c in pending)
            chars = sum(len(c.text.strip())+1 for c in pending)+len(item.text.strip())
            if span > max_seconds or gap > max_gap or chars > 12000:
                emit()
        pending.append(item)
        duration = max(c.end for c in pending)-pending[0].start
        if duration >= target_seconds and re.search(r'[.!?]["\u201d\u2019]*$', item.text.strip()):
            emit()
    if pending:
        emit()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--target-seconds", type=float, default=20)
    parser.add_argument("--max-seconds", type=float, default=40)
    parser.add_argument("--max-gap", type=float, default=3)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("output exists; choose a new dataset version")
        result = windows(json.loads(args.input.read_text()), args.target_seconds,
                         args.max_seconds, args.max_gap)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(args.output, result)
        print(f"Wrote {len(result)} windows to {args.output}")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
