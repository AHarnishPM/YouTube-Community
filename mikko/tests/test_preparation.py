import json
from pathlib import Path
import tempfile
import unittest
from claim_detection.prepare import windows
from claim_detection.annotate import label, load_journal, merge


class WindowTests(unittest.TestCase):
    def doc(self, captions):
        return {"video_id":"demo", "captions":captions, "synthetic":True}

    def test_sentence_boundary_and_stable_ids(self):
        doc = self.doc([{"start":0,"duration":10,"text":"First part"},
                        {"start":10,"duration":11,"text":"ends here."},
                        {"start":21,"duration":4,"text":"Next."}])
        result = windows(doc)
        self.assertEqual([(r["start"], r["end"]) for r in result], [(0,21),(21,25)])
        self.assertEqual(result[0]["text"], "First part ends here.")
        self.assertEqual(result, windows(doc))
        doc["captions"][0]["text"] = "Changed"
        self.assertNotEqual(result[0]["segment_id"], windows(doc)[0]["segment_id"])

    def test_gap_and_overlapping_captions(self):
        doc = self.doc([{"start":0,"end":10,"text":"one"},
                        {"start":8,"end":12,"text":"two"},
                        {"start":20,"end":25,"text":"three"}])
        self.assertEqual([(r["start"],r["end"]) for r in windows(doc)], [(0,12),(20,25)])

    def test_invalid_order_and_oversized_caption(self):
        for captions in [[{"start":0,"duration":41,"text":"long"}],
                         [{"start":5,"duration":1,"text":"a"}, {"start":0,"duration":1,"text":"b"}]]:
            with self.assertRaises(ValueError): windows(self.doc(captions))


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(segment_id="s1",video_id="v",start=0,end=10,text="Example.",label=True),
                     dict(segment_id="s2",video_id="v",start=10,end=20,text="Other.",label=False)]

    def test_resume_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"labels.jsonl"
            answers = iter(["n", "opinion", "q"])
            displayed = []
            label(self.rows,path,"data","mikko","guide",ask=lambda _:next(answers),show=displayed.append)
            self.assertFalse(any("True" in s or "label" in s for s in displayed))
            answers = iter(["y", "checkable"])
            records = label(self.rows,path,"data","mikko","guide",ask=lambda _:next(answers),show=lambda _:None)
            self.assertEqual([r["label"] for r in merge(self.rows,records)], [False,True])
            self.assertEqual(len(path.read_text().splitlines()), 2)

    def test_reject_wrong_dataset_or_guidelines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"labels.jsonl"
            answers=iter(["u","ambiguous","q"])
            records=label(self.rows,path,"data","mikko","guide",ask=lambda _:next(answers),show=lambda _:None)
            with self.assertRaises(ValueError): merge(self.rows,records)
            with self.assertRaises(ValueError): load_journal(path,"changed","mikko","guide")
            with self.assertRaises(ValueError): load_journal(path,"data","mikko","changed")
