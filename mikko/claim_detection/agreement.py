"""Compare independent annotation journals without discarding uncertain cases silently."""
import argparse
import json
from pathlib import Path


def read_journal(path):
    records = {}
    for line in Path(path).read_text().splitlines():
        row = json.loads(line)
        if row["segment_id"] in records:
            raise ValueError("duplicate journal IDs")
        if row["label"] is not None and type(row["label"]) is not bool:
            raise ValueError("journal labels must be booleans or null")
        records[row["segment_id"]] = row
    if not records:
        raise ValueError("empty journal")
    return records


def compare(left, right):
    if set(left) != set(right):
        raise ValueError("journals must cover the same segment IDs")
    for field in ("dataset_sha256", "guidelines_sha256"):
        values = {r[field] for r in [*left.values(), *right.values()]}
        if len(values) != 1:
            raise ValueError(f"journals have differing {field}")
    left_authors = {r["annotator"] for r in left.values()}
    right_authors = {r["annotator"] for r in right.values()}
    if len(left_authors) != 1 or len(right_authors) != 1 or left_authors == right_authors:
        raise ValueError("need two distinct, consistent annotator identities")
    pairs = [(left[k], right[k]) for k in sorted(left)]
    resolved = [(a,b) for a,b in pairs if type(a["label"]) is bool and type(b["label"]) is bool]
    n = len(resolved)
    observed = sum(a["label"] == b["label"] for a,b in resolved)/n if n else None
    p_left = sum(a["label"] for a,b in resolved)/n if n else None
    p_right = sum(b["label"] for a,b in resolved)/n if n else None
    expected = p_left*p_right+(1-p_left)*(1-p_right) if n else None
    kappa = (observed-expected)/(1-expected) if n and expected < 1 else None
    return {"total":len(pairs), "both_definite":n, "uncertain_pairs":len(pairs)-n,
            "raw_agreement":observed, "cohen_kappa":kappa,
            "needs_review":[{"segment_id":a["segment_id"],
                             "left_label":a["label"], "right_label":b["label"],
                             "left_rationale":a["rationale"], "right_rationale":b["rationale"]}
                            for a,b in pairs if a["label"] is None or b["label"] is None or a["label"] != b["label"]],
            "note":"Agreement/kappa use only pairs with two boolean labels; null kappa is undefined."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compare(read_journal(args.left), read_journal(args.right))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps(result, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
