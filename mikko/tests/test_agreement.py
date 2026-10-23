import unittest
from claim_detection.agreement import compare


def journal(author, labels):
    return {str(i):dict(segment_id=str(i),label=value,annotator=author,
                       rationale="human note",dataset_sha256="data",guidelines_sha256="guide")
            for i,value in enumerate(labels)}


class AgreementTests(unittest.TestCase):
    def test_known_kappa(self):
        result=compare(journal("a",[True,True,False,False]),journal("b",[True,False,True,False]))
        self.assertEqual(result["raw_agreement"],0.5)
        self.assertEqual(result["cohen_kappa"],0)
        self.assertEqual(len(result["needs_review"]),2)

    def test_uncertain_and_degenerate(self):
        result=compare(journal("a",[True,None]),journal("b",[True,False]))
        self.assertEqual(result["uncertain_pairs"],1)
        self.assertIsNone(result["cohen_kappa"])
        self.assertEqual(len(result["needs_review"]),1)

    def test_reject_self_comparison(self):
        with self.assertRaises(ValueError): compare(journal("a",[True]),journal("a",[False]))
