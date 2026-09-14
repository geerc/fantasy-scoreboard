import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import ImageChops

from layout_config import add_layout_arguments, resolve_layout
from test_scoreboard import PROJECT_DIR
import test_scoreboard_replay
from name_scroll import NameRenderer


class LayoutTests(unittest.TestCase):
    def test_config_and_cli_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "board.json"
            path.write_text(json.dumps({"layout": "diagonal"}))
            self.assertEqual(resolve_layout(config=path), "diagonal")
            self.assertEqual(resolve_layout("classic", path), "classic")
            path.write_text(json.dumps({"layout": "bad-layout"}))
            with self.assertRaises(ValueError):
                resolve_layout(config=path)
            path.write_text("[]")
            with self.assertRaises(ValueError):
                resolve_layout(config=path)

    def test_missing_default_is_classic_but_explicit_missing_file_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.json"
            with patch("layout_config.DEFAULT_CONFIG", missing):
                self.assertEqual(resolve_layout(), "classic")
            with self.assertRaises(OSError):
                resolve_layout(config=missing)

    def test_cli_options(self):
        parser = argparse.ArgumentParser()
        add_layout_arguments(parser)
        args = parser.parse_args(["--layout", "diagonal", "--config", "custom.json"])
        self.assertEqual(args.layout, "diagonal")
        self.assertEqual(args.config, Path("custom.json"))

    def test_long_team_names_are_truncated_with_ellipsis(self):
        renderer = NameRenderer(PROJECT_DIR / "rpi-rgb-led-matrix/fonts/4x6.bdf")
        display_name = renderer.fit_team_name("The Spotted Lantern Flies", 30)
        self.assertTrue(display_name.endswith("..."))
        self.assertLessEqual(renderer.text_width(display_name[:-3]) + 5, 30)
        self.assertEqual(renderer.fit_team_name("Chowder", 30), "Chowder")
        for align in (True, False):
            actual = renderer.team_window("The Spotted Lantern Flies", 30, align)
            expected = renderer.window(display_name, 30, right_align=align)
            if align:
                self.assertEqual([actual.getpixel((x, 4)) for x in range(25, 30)],
                                 [(255, 255, 255), (0, 0, 0), (255, 255, 255),
                                  (0, 0, 0), (255, 255, 255)])
            self.assertEqual(actual.size, expected.size)

    def render(self, layout):
        replay = test_scoreboard_replay.ReplayTests()
        replay.setUp()
        return replay.render_headless(replay.fixture, layout=layout, rotation_interval=1000)

    def test_classic_names_do_not_move(self):
        _, matrix = self.render("classic")
        calls = matrix.CreateFrameCanvas.return_value.SetImage.call_args_list
        for side_index in (2, 3):
            first = calls[side_index].args[0]
            for call in calls[side_index::4]:
                self.assertIsNone(ImageChops.difference(first, call.args[0]).getbbox())
        matrix.SetImage.assert_not_called()

    def test_diagonal_shows_median_medals_in_opposite_corners(self):
        replay = test_scoreboard_replay.ReplayTests()
        replay.setUp()
        fixture = deepcopy(replay.fixture)
        fixture["league_average_match"] = True
        _, matrix = replay.render_headless(
            fixture, layout="diagonal", rotation_interval=1)
        positions = [call.args[1:3]
                     for call in matrix.CreateFrameCanvas.return_value.SetImage.call_args_list]
        self.assertIn((43, 0), positions)
        self.assertIn((13, 24), positions)

    def test_diagonal_positions_scrolling_and_score_alignment(self):
        graphics, matrix = self.render("diagonal")
        calls = matrix.CreateFrameCanvas.return_value.SetImage.call_args_list
        for index in range(0, len(calls), 4):
            frame = calls[index:index + 4]
            self.assertEqual([c.args[1:] for c in frame],
                             [(2, 2, False), (50, 18, False),
                              (16, 9, False), (2, 18, False)])
            self.assertEqual([c.args[0].size for c in frame],
                             [(12, 12), (12, 12), (46, 6), (46, 6)])
        first = calls[2].args[0]
        self.assertTrue(all(ImageChops.difference(first, c.args[0]).getbbox() is None
                            for c in calls[6::4]))
        text_calls = graphics.DrawText.call_args_list
        for index in range(0, len(text_calls), 4):
            left, left_bold, right, right_bold = text_calls[index:index + 4]
            self.assertEqual(left.args[2:4], (16, 7))
            self.assertEqual(left_bold.args[2], left.args[2] + 1)
            self.assertEqual(right.args[3], 31)
            self.assertEqual(right_bold.args[2], right.args[2] + 1)
            self.assertEqual(right_bold.args[2] + len(right.args[5]) * 5, 48)
            self.assertIs(left.args[1], right.args[1])
        matrix.SetImage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
