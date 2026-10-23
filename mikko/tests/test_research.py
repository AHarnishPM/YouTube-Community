import json
from pathlib import Path
import tempfile
import unittest
from claim_detection.evaluation import read_rows, evaluate, write_jsonl
from claim_detection.detectors import RuleDetector, OllamaDetector, InferenceError
from claim_detection.core import Segment
from claim_detection.research import audit, sweep


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.rows = read_rows(Path(__file__).parents[1] / "data/examples/claims.jsonl")

    def test_audit_counts_and_missing_labels(self):
        result = audit(self.rows)
        self.assertEqual(result["splits"]["dev"]["positive"], 2)
        self.assertEqual(result["synthetic_examples"], 8)
        self.rows[0]["label"] = None
        self.assertEqual(audit(self.rows)["splits"]["train"]["unlabeled_or_invalid"], 1)

    def test_duplicate_text_warning(self):
        self.rows[-1]["text"] = self.rows[0]["text"].upper()
        self.assertTrue(any("across splits" in w for w in audit(self.rows)["warnings"]))

    def test_sweep_uses_cached_scores_and_rejects_test(self):
        predictions, report = evaluate(self.rows, RuleDetector(), "dev", 0.5)
        report["run"] = {"split": "dev"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            write_jsonl(path / "predictions.jsonl", predictions)
            (path / "metrics.json").write_text(json.dumps(report))
            result = sweep(path)
            self.assertEqual(len(result["thresholds"]), 21)
            self.assertEqual(result["selected"]["threshold"], 0.95)
            self.assertAlmostEqual(result["selected"]["f1"], 2/3)
            report["run"]["split"] = "test"
            (path / "metrics.json").write_text(json.dumps(report))
            with self.assertRaises(ValueError): sweep(path)

    def test_nonobject_model_envelope(self):
        for response in [None, [], "bad"]:
            detector = OllamaDetector(transport=lambda *args: response)
            with self.assertRaises(InferenceError):
                detector.score(Segment("s", "v", 0, 1, "hello"))
