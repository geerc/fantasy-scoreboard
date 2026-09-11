import contextlib
from copy import deepcopy
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests
import test_scoreboard as replay


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = replay.load_fixture(replay.DEFAULT_FIXTURE)

    def test_historical_fixture(self):
        self.assertEqual(self.fixture["season"], "2025")
        self.assertEqual(self.fixture["week"], 8)
        self.assertEqual(len(self.fixture["matchups"]), 10)
        self.assertEqual(self.fixture["matchups"][0]["points"], 139.94)

    def test_adapter_returns_independent_copies(self):
        league = replay.FixtureLeague(self.fixture)
        league.get_matchups(8)[0]["points"] = 0
        self.assertEqual(league.get_matchups(8)[0]["points"], 139.94)
        for user in league.get_users():
            self.assertNotIn("avatar", user["metadata"])
        with self.assertRaises(ValueError):
            league.get_matchups(9)

    def test_replay_blocks_http_and_restores_context(self):
        old_dir = Path.cwd()
        original_league = replay.scoreboard.League
        def try_http():
            requests.get("https://example.invalid/")
        with patch.object(replay.scoreboard, "main", side_effect=try_http):
            with self.assertRaisesRegex(RuntimeError, "HTTP is disabled"):
                replay.run_replay(self.fixture)
        self.assertEqual(Path.cwd(), old_dir)
        self.assertIs(replay.scoreboard.League, original_league)

    def render_headless(self, fixture, layout="classic", rotation_interval=1):
        canvas = Mock()
        matrix = Mock(width=64)
        matrix.CreateFrameCanvas.return_value = canvas
        matrix.SwapOnVSync.return_value = canvas
        graphics = Mock()
        graphics.Font.return_value.CharacterWidth.return_value = 5
        emulator = SimpleNamespace(
            RGBMatrix=Mock(return_value=matrix),
            RGBMatrixOptions=SimpleNamespace,
            graphics=graphics,
        )
        clock = [0]
        sleeps = [0]
        def now():
            clock[0] += 0.25
            return clock[0]
        def sleep(_):
            sleeps[0] += 1
            if sleeps[0] >= 20:
                raise KeyboardInterrupt
        with patch.dict("sys.modules", {"RGBMatrixEmulator": emulator}), \
                patch.object(replay.scoreboard.time, "monotonic", side_effect=now), \
                patch.object(replay.scoreboard.time, "sleep", side_effect=sleep), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                replay.run_replay(fixture, rotation_interval=rotation_interval,
                                  data_refresh_interval=1, layout=layout)
        return graphics, matrix

    def test_production_renderer_rotates_and_refreshes_offline(self):
        graphics, matrix = self.render_headless(self.fixture)
        rendered_text = [call.args[5] for call in graphics.DrawText.call_args_list]
        self.assertIn("139.94", rendered_text)
        self.assertIn("171.42", rendered_text)
        self.assertGreater(matrix.SwapOnVSync.call_count, 5)

    def test_empty_preseason_screen(self):
        fixture = deepcopy(self.fixture)
        fixture["matchups"] = []
        fixture["season_type"] = "pre"
        graphics, _ = self.render_headless(fixture)
        rendered_text = [call.args[5] for call in graphics.DrawText.call_args_list]
        self.assertIn("NO MATCHUPS", rendered_text)
        self.assertIn("PRESEASON", rendered_text)
        self.assertNotIn("WEEK 8", rendered_text)


if __name__ == "__main__":
    unittest.main()
