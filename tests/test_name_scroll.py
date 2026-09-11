import unittest

from PIL import Image, ImageChops

from name_scroll import NameRenderer
from test_scoreboard import PROJECT_DIR
import test_scoreboard_replay


class NameScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = NameRenderer(PROJECT_DIR / "rpi-rgb-led-matrix/fonts/4x6.bdf")

    def test_actual_font_width_and_short_names_remain_static(self):
        self.assertEqual(self.renderer.text_width("ABCDE"), 20)
        for right_align in (False, True):
            first = self.renderer.window("Short", 30, 0, right_align)
            later = self.renderer.window("Short", 30, 100, right_align)
            self.assertIsNone(ImageChops.difference(first, later).getbbox())

    def test_long_names_move_and_wrap_exactly(self):
        name = "The Spotted Lantern Flies"
        period = self.renderer.text_width(name) + self.renderer.GAP
        first = self.renderer.window(name, 30, 0)
        moved = self.renderer.window(name, 30, 5)
        wrapped = self.renderer.window(name, 30, period)
        self.assertIsNotNone(ImageChops.difference(first, moved).getbbox())
        self.assertIsNone(ImageChops.difference(first, wrapped).getbbox())

    def test_clipping_never_touches_other_regions(self):
        name = "Very long team name that must stay in its own block"
        sentinel = (12, 34, 56)
        for phase in range(self.renderer.text_width(name) + self.renderer.GAP):
            board = Image.new("RGB", (64, 32), sentinel)
            for x in (1, 33):
                board.paste(self.renderer.window(name, 30, phase), (x, 17))
            for x in (0, 31, 32, 63):
                self.assertTrue(all(board.getpixel((x, y)) == sentinel for y in range(32)))
            self.assertTrue(all(board.getpixel((x, y)) == sentinel
                                for x in range(64) for y in (16, 23)))

    def test_empty_and_unsupported_unicode_are_safe(self):
        self.assertIsNone(self.renderer.window(None, 30).getbbox())
        self.assertEqual(self.renderer.window("Team 🏈", 30).size, (30, 6))

    def test_production_only_publishes_complete_frames(self):
        replay = test_scoreboard_replay.ReplayTests()
        replay.setUp()
        _, matrix = replay.render_headless(replay.fixture)
        matrix.SetImage.assert_not_called()
        matrix.Clear.assert_not_called()
        canvas = matrix.CreateFrameCanvas.return_value
        calls = canvas.SetImage.call_args_list
        self.assertGreater(len(calls), 4)
        for start in range(0, len(calls), 4):
            frame = calls[start:start + 4]
            self.assertEqual([c.args[1:] for c in frame],
                             [(1, 1, False), (48, 1, False),
                              (1, 17, False), (33, 17, False)])
            self.assertEqual(frame[2].args[0].size, (30, 6))
            self.assertEqual(frame[3].args[0].size, (30, 6))
        self.assertEqual(matrix.SwapOnVSync.call_count, len(calls) // 4)


if __name__ == "__main__":
    unittest.main()
