"""Blind terminal labeling with resumable, dataset-bound human annotation records.

No model predictions or preexisting labels are displayed. 'Unsure' is preserved
for adjudication and cannot be exported as an evaluated boolean label.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from .evaluation import read_rows, write_jsonl, digest


def load_journal(path, dataset_hash, annotator, guidelines_hash):
    records = {}
    if not path.exists():
        return records
    for line in path.read_text().splitlines():
        record = json.loads(line)
        if (record["dataset_sha256"], record["annotator"], record["guidelines_sha256"]) != (
                dataset_hash, annotator, guidelines_hash):
            raise ValueError("journal belongs to another dataset, annotator, or guideline version")
        if record["segment_id"] in records:
            raise ValueError("duplicate annotation record")
        if record["label"] is not None and type(record["label"]) is not bool:
            raise ValueError("invalid journal label")
        if not isinstance(record.get("rationale"), str) or not record["rationale"].strip():
            raise ValueError("annotation needs a rationale")
        records[record["segment_id"]] = record
    return records


def merge(rows, records):
    expected = {r["segment_id"] for r in rows}
    if set(records) != expected:
        raise ValueError("journal must cover exactly the dataset IDs before export")
    if any(type(r["label"]) is not bool for r in records.values()):
        raise ValueError("unsure annotations need human adjudication before export")
    return [{**r, "label": records[r["segment_id"]]["label"],
             "annotation": records[r["segment_id"]]} for r in rows]


def label(rows, path, dataset_hash, annotator, guidelines_hash, ask=input, show=print):
    records = load_journal(path, dataset_hash, annotator, guidelines_hash)
    if not set(records) <= {r["segment_id"] for r in rows}:
        raise ValueError("journal contains unknown segment IDs")
    path.parent.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows):
        if row["segment_id"] in records:
            continue
        show(f"\n{index+1}/{len(rows)} | {row['video_id']} | {row['start']:.1f}–{row['end']:.1f}s")
        show(row["text"])
        while True:
            answer = ask("Context-worthy? [y]es / [n]o / [u]nsure / [q]uit: ").strip().lower()
            if answer in ("y", "n", "u", "q"):
                break
        if answer == "q":
            break
        rationale = ""
        while not rationale:
            rationale = ask("Short rationale: ").strip()
        record = {"segment_id": row["segment_id"], "label": {"y":True, "n":False, "u":None}[answer],
                  "rationale": rationale, "annotator": annotator,
                  "dataset_sha256": dataset_hash, "guidelines_sha256": guidelines_hash,
                  "created_at": datetime.now(timezone.utc).isoformat()}
        with path.open("a") as stream:
            stream.write(json.dumps(record, ensure_ascii=False)+"\n")
        records[row["segment_id"]] = record
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["label", "export"])
    parser.add_argument("input", type=Path)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--annotator", required=True)
    parser.add_argument("--guidelines", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if not args.annotator.strip() or not args.guidelines.read_text().strip():
            raise ValueError("supply annotator name and your written annotation guidelines")
        rows = read_rows(args.input)
        data_hash, guide_hash = digest(args.input.read_bytes()), digest(args.guidelines.read_bytes())
        if args.command == "label":
            label(rows, args.journal, data_hash, args.annotator, guide_hash)
        else:
            if args.output is None or args.output.exists():
                raise ValueError("export requires a new --output path")
            records = load_journal(args.journal, data_hash, args.annotator, guide_hash)
            result = merge(rows, records)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            write_jsonl(args.output, result)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    except (EOFError, KeyboardInterrupt):
        parser.exit(0, "\nSaved annotations retained; rerun to resume.\n")


if __name__ == "__main__":
    main()
