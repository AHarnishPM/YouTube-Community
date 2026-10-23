import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from claim_detection.api import app
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, "Install .[api,test] for API contract tests")
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.row = {"segment_id":"s1", "video_id":"v1", "start":0, "end":10,
                    "text":"The study found a 30 percent increase."}

    def test_success(self):
        response = self.client.post("/v1/claims/detect", json={"segments":[self.row]})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["schema_version"], "1.0")
        self.assertTrue(body["predictions"][0]["is_context_worthy"])
        self.assertEqual(body["predictions"][0]["segment_id"], "s1")

    def test_bad_input(self):
        for body in [{"segments":[]}, {"segments":[self.row]*2},
                     {"segments":[{**self.row, "end":0}]},
                     {"segments":[{**self.row, "text":" "}]},
                     {"segments":[self.row], "threshold":1.1}]:
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/v1/claims/detect", json=body).status_code, 422)

    def test_model_failure(self):
        from claim_detection.detectors import InferenceError
        with patch("claim_detection.api.make_detector") as factory:
            factory.return_value.score.side_effect = InferenceError("bad json")
            response = self.client.post("/v1/claims/detect", json={"segments":[self.row], "detector":"ollama"})
        self.assertEqual(response.status_code, 503)
