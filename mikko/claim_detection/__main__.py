import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import time
from .core import Segment, detect, probability
from .detectors import make_detector, InferenceError
from .evaluation import read_rows, write_jsonl, assign_splits, evaluate, digest


def main():
    parser = argparse.ArgumentParser(description="Mikko claim detection tools")
    parser.add_argument("command", choices=["predict", "split", "evaluate"])
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--detector", choices=["rules", "ollama"], default="rules")
    parser.add_argument("--model", default="llama3.2:3b")
    parser.add_argument("--model-digest", help="Record Ollama model digest for reproducibility")
    parser.add_argument("--prompt-file")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--split", choices=["train", "dev", "test"], default="dev")
    parser.add_argument("--seed", type=int, default=4701)
    parser.add_argument("--allow-test", action="store_true", help="Explicitly unlock held-out evaluation")
    args = parser.parse_args()
    try:
        probability(args.threshold)
        rows = read_rows(args.input)
        if args.output.exists():
            raise ValueError("output already exists; choose a new name to preserve experiment history")
        if args.command == "split":
            result = assign_splits(rows, args.seed)
        else:
            detector = make_detector(args.detector, args.model, args.prompt_file)
            if args.command == "predict":
                result = [detect(Segment.from_dict(r), detector, args.threshold) for r in rows]
            else:
                if args.split == "test" and not args.allow_test:
                    raise ValueError("freeze the configuration before using --allow-test")
                started = time.monotonic()
                model_metadata = detector.metadata() if hasattr(detector, "metadata") else None
                if args.model_digest and model_metadata and args.model_digest != model_metadata["digest"]:
                    raise ValueError("requested model digest differs from installed model")
                predictions, report = evaluate(rows, detector, args.split, args.threshold)
                report["run"] = {"created_at": datetime.now(timezone.utc).isoformat(),
                    "input_sha256": digest(args.input.read_bytes()), "detector": detector.name,
                    "threshold": args.threshold, "split": args.split,
                    "model_digest": model_metadata["digest"] if model_metadata else args.model_digest,
                    "model_metadata": model_metadata,
                    "source_sha256": {p.name: digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))},
                    "prompt_sha256": digest(getattr(detector, "prompt", "").encode()),
                    "python": platform.python_version(), "elapsed_seconds": time.monotonic()-started,
                    "synthetic_fixture": all(r.get("synthetic") is True for r in rows)}
                args.output.mkdir(parents=True)
                write_jsonl(args.output / "predictions.jsonl", predictions)
                (args.output / "metrics.json").write_text(json.dumps(report, indent=2)+"\n")
                (args.output / "prompt.txt").write_text(getattr(detector, "prompt", "rules-v1; see detectors.py"))
                print(json.dumps(report, indent=2))
                return
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(args.output, result)
    except (ValueError, KeyError, TypeError, OSError, InferenceError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
