import json
import tempfile
import unittest
from pathlib import Path

from win_probability import (estimate_uncertainty,
                             resolve_win_probability_settings,
                             show_probability_phase,
                             simulate_matchup,
                             update_matchup_probabilities,
                             WinProbabilitySettings)


class WinProbabilityTests(unittest.TestCase):
    @staticmethod
    def team(roster_id, points, projection):
        return {"roster_id": roster_id, "points": points,
                "projection": projection}

    def test_simulation_is_deterministic_and_favors_stronger_projection(self):
        first = self.team("1", 70, 132)
        second = self.team("2", 68, 108)
        result = simulate_matchup(first, second, 5000)
        self.assertEqual(result, simulate_matchup(first, second, 5000))
        self.assertGreater(result[0], 50)
        self.assertAlmostEqual(sum(result), 100)

    def test_completed_matchup_is_exact_and_tie_is_split(self):
        self.assertEqual(simulate_matchup(
            self.team("1", 101, 101), self.team("2", 99, 99), 1000),
            (100, 0))
        self.assertEqual(simulate_matchup(
            self.team("1", 101, 101), self.team("2", 101, 101), 1000),
            (50, 50))

    def test_probabilities_are_attached_to_matchup(self):
        matchup = {"team1": self.team("1", 50, 110),
                   "team2": self.team("2", 45, 100)}
        update_matchup_probabilities([matchup], 500, {"1": 5, "2": 5})
        self.assertIn("win_probability", matchup["team1"])
        self.assertEqual(
            matchup["team1"]["win_probability"] +
            matchup["team2"]["win_probability"], 100)

    def test_uncertainty_shrinks_to_zero_at_final_score(self):
        self.assertGreater(estimate_uncertainty(20, 100), 0)
        self.assertEqual(estimate_uncertainty(100, 100), 0)

    def test_config_defaults_overrides_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "board.json"
            path.write_text(json.dumps({
                "show_win_probability": True,
                "win_probability_display": "probability",
                "win_probability_simulations": 2500,
            }))
            settings = resolve_win_probability_settings(config=path)
            self.assertTrue(settings.enabled)
            self.assertEqual(settings.display, "probability")
            self.assertEqual(settings.simulations, 2500)
            self.assertEqual(
                resolve_win_probability_settings(False, 1000, path).simulations,
                1000)

            path.write_text(json.dumps({"win_probability_simulations": 10}))
            with self.assertRaisesRegex(ValueError, "100 to 100000"):
                resolve_win_probability_settings(config=path)

    def test_alternate_phase_uses_each_matchups_halfway_point(self):
        settings = WinProbabilitySettings(True, "alternate", 5000)
        self.assertFalse(show_probability_phase(settings, 0, 10))
        self.assertFalse(show_probability_phase(settings, 4.99, 10))
        self.assertTrue(show_probability_phase(settings, 5, 10))
        self.assertTrue(show_probability_phase(settings, 9.99, 10))
        self.assertFalse(show_probability_phase(settings, 7, 10, available=False))

        continuous = WinProbabilitySettings(True, "probability", 5000)
        self.assertTrue(show_probability_phase(continuous, 0, 10))


if __name__ == "__main__":
    unittest.main()
