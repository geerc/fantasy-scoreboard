from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from live_projections import (calculate_team_outlooks, calculate_team_projections, clock_seconds,
                              league_median, projected_final, projection_field,
                              remaining_fraction)
from main import decode_logo, open_logo_or_default, user_avatar_url


class LiveProjectionTests(unittest.TestCase):
    def test_league_median_averages_middle_scores(self):
        self.assertEqual(league_median({"1": 90, "2": 120, "3": 100, "4": 80}), 95)
        self.assertEqual(league_median({"1": 90, "2": 120, "3": 100}), 100)
        self.assertIsNone(league_median({"1": 90}))

    def test_avatar_url_prefers_custom_logo_then_standard_avatar(self):
        self.assertEqual(user_avatar_url({
            "avatar": "profile", "metadata": {"avatar": "https://custom/logo.jpg"}
        }), "https://custom/logo.jpg")
        self.assertEqual(user_avatar_url({"avatar": "profile", "metadata": {}}),
                         "https://sleepercdn.com/avatars/profile")
        self.assertIsNone(user_avatar_url({"avatar": None, "metadata": None}))

    def test_invalid_logo_falls_back_without_crashing(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            invalid = folder / "invalid.png"
            invalid.write_text("not an image")
            fallback = folder / "default.jpg"
            Image.new("RGB", (4, 4), (12, 34, 56)).save(fallback, "PNG")
            loaded = open_logo_or_default(invalid, fallback)
            self.assertEqual(loaded.getpixel((0, 0)), (12, 34, 56))
            missing = open_logo_or_default(invalid, folder / "missing.jpg")
            self.assertEqual(missing.size, (20, 20))

    def test_downloaded_logo_bytes_are_validated(self):
        content = BytesIO()
        Image.new("RGB", (3, 3), (1, 2, 3)).save(content, "PNG")
        self.assertEqual(decode_logo(content.getvalue()).getpixel((0, 0)), (1, 2, 3))
        with self.assertRaises(OSError):
            decode_logo(b"not an image")

    def test_clock_and_remaining_regulation_fraction(self):
        self.assertEqual(clock_seconds("12:34"), 754)
        self.assertEqual(remaining_fraction({"state": "pre"}), 1)
        self.assertEqual(remaining_fraction({"state": "post"}), 0)
        self.assertEqual(remaining_fraction(
            {"state": "in", "period": 2, "clock": "0:00"}), 0.5)
        self.assertAlmostEqual(remaining_fraction(
            {"state": "in", "period": 4, "clock": "7:30"}), 0.125)
        self.assertEqual(remaining_fraction(
            {"state": "in", "period": 5, "clock": "10:00"}), 0)

    def test_projected_final_by_game_state(self):
        self.assertEqual(projected_final(0, 16, {"state": "pre"}), 16)
        self.assertEqual(projected_final(
            10, 16, {"state": "in", "period": 2, "clock": "0:00"}), 18)
        self.assertEqual(projected_final(22, 16, {"state": "post"}), 22)
        self.assertEqual(projected_final(22, 16, None), 22)

    def test_scoring_format_selection(self):
        self.assertEqual(projection_field({"rec": 0}), "pts_std")
        self.assertEqual(projection_field({"rec": 0.5}), "pts_half_ppr")
        self.assertEqual(projection_field({"rec": 1}), "pts_ppr")

    def test_team_total_combines_pre_live_and_final_players(self):
        matchups = [{
            "roster_id": 7,
            "starters": ["live", "waiting", "done"],
            "players_points": {"live": 10, "waiting": 0, "done": 23},
        }]
        players = {
            "live": {"team": "DET"},
            "waiting": {"team": "WSH"},
            "done": {"team": "BUF"},
        }
        projections = {
            "live": {"pts_half_ppr": 16},
            "waiting": {"pts_half_ppr": 8},
            "done": {"pts_half_ppr": 19},
        }
        games = {
            "DET": {"state": "in", "period": 2, "clock": "0:00"},
            "WAS": {"state": "pre"},
            "BUF": {"state": "post"},
        }
        self.assertEqual(calculate_team_projections(
            matchups, players, projections, games, {"rec": 0.5}), {"7": 49.0})

    def test_uncertainty_only_includes_remaining_starter_games(self):
        matchups = [{"roster_id": 7, "starters": ["qb", "wr"],
                     "players_points": {"qb": 10, "wr": 8}}]
        players = {"qb": {"team": "BUF", "position": "QB"},
                   "wr": {"team": "DAL", "position": "WR"}}
        projections = {"qb": {"pts_ppr": 20}, "wr": {"pts_ppr": 16}}
        games = {"BUF": {"state": "in", "period": 3, "clock": "15:00"},
                 "DAL": {"state": "post"}}
        totals, uncertainties = calculate_team_outlooks(
            matchups, players, projections, games, {"rec": 1})
        self.assertEqual(totals, {"7": 28.0})
        self.assertGreater(uncertainties["7"], 0)

        games["BUF"] = {"state": "post"}
        _, uncertainties = calculate_team_outlooks(
            matchups, players, projections, games, {"rec": 1})
        self.assertEqual(uncertainties, {"7": 0.0})


if __name__ == "__main__":
    unittest.main()
