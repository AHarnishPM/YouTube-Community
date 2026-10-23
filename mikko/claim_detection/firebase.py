"""Convert an existing Firebase subtitle export to canonical detector input.

No Firebase credentials, network reads, writes, or ingestion replacement. One
input line remains one target. IDs are local proposals until the team agrees on
an identifier shared with retrieval; retain source_line_index for that mapping.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from .core import Segment
from .evaluation import digest, write_jsonl


def convert(transcript, video_id=None):
    if not isinstance(transcript, dict):
        raise ValueError("expected the Firebase transcript object")
    embedded = transcript.get("videoId")
    if video_id and embedded and video_id != embedded:
        raise ValueError("video ID disagrees with the exported transcript")
    video = video_id or embedded
    if not isinstance(video, str) or not video.strip():
        raise ValueError("provide --video-id for exports from /videos/{videoId}/transcript")
    lines = transcript.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ValueError("expected a nonempty lines array")
    language = transcript.get("languageCode", "unknown")
    if not isinstance(language, str) or not language.strip():
        raise ValueError("languageCode must be nonempty text")
    records = []
    for index, line in enumerate(lines):
        try:
            if not isinstance(line, dict):
                raise ValueError("line must be an object")
            start, duration, text = line["start"], line["duration"], line["text"]
            if type(duration) not in (int, float) or duration <= 0:
                raise ValueError("duration must be positive; resolve missing timestamps upstream")
            if type(start) not in (int, float):
                raise ValueError("start must be numeric seconds")
            # Exclude fetchedAt: fetching identical captions again must retain IDs.
            identity = json.dumps([video, language, index, start, duration, text],
                                  ensure_ascii=False, allow_nan=False)
            identifier = f"{video}:line-v1:{index}:{digest(identity.encode())[:16]}"
            segment = Segment(identifier, video, start, start+duration, text)
            if records and start < records[-1]["start"]:
                raise ValueError("lines must be ordered by start time")
            records.append({**asdict(segment), "source_line_index":index,
                            "source_duration":duration, "language":language,
                            "segmentation_version":"firebase-lines-v1",
                            "caption_source":"firebase-subtitle-export"})
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"line {index}: {exc}") from exc
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--video-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("output already exists; choose a new export version")
        rows = convert(json.loads(args.input.read_text()), args.video_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(args.output, rows)
        print(f"Wrote {len(rows)} subtitle targets, preserving input line boundaries.")
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
