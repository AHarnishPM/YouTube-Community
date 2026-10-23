import unittest
from claim_detection.corpus import parse_vtt, Tracks, seconds


class CaptionTests(unittest.TestCase):
    def test_cues_settings_and_markup(self):
        text='WEBVTT\n\nNOTE ignored\ncomment\n\ncue-1\n00:00:01.500 --> 00:00:03.000 align:start\n<v Speaker>Hello &amp;\nwelcome.</v>\n'
        self.assertEqual(parse_vtt(text),[dict(start=1.5,end=3.0,text='Hello & welcome.')])

    def test_invalid_and_empty(self):
        for text in ['<html>error</html>','WEBVTT\n\n','WEBVTT\n\n00:00:99.000 --> 00:02:00.000\ntext']:
            with self.assertRaises(ValueError): parse_vtt(text)

    def test_tracks(self):
        parser=Tracks()
        parser.feed('<iframe src="https://www.youtube.com/embed/J7DzL2_Na80"></iframe><track srclang="en" src="/captions.vtt">')
        self.assertEqual(parser.videos,{'J7DzL2_Na80'})
        self.assertEqual(parser.captions,['/captions.vtt'])
        self.assertEqual(seconds('01:02:03.456'),3723.456)
