"""验证重复、补全、误识别、位置隔离、一对一和缺失边界。"""
import unittest

from cv_engine.stages.s07_items import merge_items


def box(text, call, *, y=10, score=.9, ts=None):
    return dict(text=text, ocr_call=call, ts=call if ts is None else ts, frame=call*30,
                score=score, poly=[[10, y], [150, y], [150, y+15], [10, y+15]])


def track(boxes, n=None):
    n = n or max(b['ocr_call'] for b in boxes)
    return merge_items(boxes, [dict(call=i, ts=i) for i in range(1, n+1)])


class ItemTests(unittest.TestCase):
    def test_duplicate_and_completion_keep_all_versions(self):
        tracks = track([box('Monetary policy', 1), box('Monetary policy is useful', 2, score=.85),
                        box('Monetary policy', 3)])
        self.assertEqual(len(tracks), 1)
        self.assertEqual(len(tracks[0]['observations']), 3)
        self.assertEqual(tracks[0]['best']['ocr_call'], 2)

    def test_low_confidence_long_text_does_not_replace(self):
        tracks = track([box('Monetary policy', 1), box('Monetary policy is useful', 2, score=.3)])
        self.assertEqual(tracks[0]['best']['ocr_call'], 1)

    def test_full_line_returns_after_partial_observation(self):
        tracks = track([box('the money supply in a society to regulate the aggregate market', 1),
                        box('regulate the aggregate market', 2),
                        box('the money supply in a society to regu the aggregate market', 3)])
        self.assertEqual(len(tracks), 1)
        self.assertEqual(len(tracks[0]['observations']), 3)

    def test_same_text_on_different_lines_and_different_text_same_line(self):
        self.assertEqual(len(track([box('policy', 1), box('policy', 2, y=40)])), 2)
        self.assertEqual(len(track([box('Monetary policy', 1), box('Fiscal spending', 2)])), 2)
        self.assertEqual(len(track([box('x', 1), box('y', 2)])), 2)

    def test_one_to_one_and_empty_calls(self):
        tracks = track([box('same words', 1), box('same words', 2), box('same words', 2)])
        self.assertEqual(len(tracks), 2)
        self.assertEqual(sorted(len(t['observations']) for t in tracks), [1, 2])
        self.assertEqual(len(track([box('same words', 1), box('same words', 4)])), 1)
        self.assertEqual(len(track([box('same words', 1), box('same words', 5)])), 2)

    def test_time_window_normalization_and_empty(self):
        tracks = merge_items([box('same words', 1), box('Same, words!', 2, ts=130)],
                             [dict(call=1, ts=1), dict(call=2, ts=130)])
        self.assertEqual(len(tracks), 2)
        self.assertEqual(len(track([box('ＡＢＣＤ', 1), box('abcd!', 2)])), 1)
        self.assertEqual(track([box('...', 1)]), [])
        self.assertEqual(merge_items([], []), [])
