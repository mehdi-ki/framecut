"""Tests for the local automatic-subtitle normalization layer."""
import threading
import unittest
from types import SimpleNamespace

from core import ExportCancelled
from transcription import normalize_segments, transcribe_media


class TranscriptionTest(unittest.TestCase):
    def test_normalize_segments_sorts_and_reports_progress(self):
        progress=[]
        segments=[
            SimpleNamespace(start=2.0, end=2.02, text='  zweiter   Cue  '),
            SimpleNamespace(start=0.5, end=1.2, text=' erster Cue\nmit Zeilenumbruch '),
            SimpleNamespace(start=4.0, end=5.0, text=''),
        ]
        cues=normalize_segments(segments,progress.append,total_duration=5)
        self.assertEqual([cue['text'] for cue in cues],['erster Cue mit Zeilenumbruch','zweiter Cue'])
        self.assertAlmostEqual(cues[0]['start'],.5)
        self.assertAlmostEqual(cues[1]['end'],2.04)
        self.assertGreater(progress[-1],24)

    def test_normalize_segments_can_be_cancelled(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(ExportCancelled):
            normalize_segments([SimpleNamespace(start=0,end=1,text='Hallo')],cancel=cancel)

    def test_invalid_model_is_rejected_before_backend_import(self):
        with self.assertRaisesRegex(ValueError,'Modellgröße'):
            transcribe_media(__file__,model_size='unknown')


if __name__=='__main__':
    unittest.main()
