import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from multi_league_config import load_multi_league_config


class MultiLeagueConfigTests(unittest.TestCase):
    def write_config(self, folder, value):
        path = Path(folder) / "board.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_legacy_config_does_not_enable_multi_league(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_config(folder, {"layout": "diagonal"})
            self.assertIsNone(load_multi_league_config(path))

    def test_users_defaults_public_and_private_espn(self):
        with tempfile.TemporaryDirectory() as folder:
            config = load_multi_league_config(self.write_config(folder, {
                "users": {"me": {"label": "Me", "sleeper_user_id": 12,
                                   "espn_owner_id": "{ABC}"}},
                "default_display_users": ["me"],
                "show_all_matchups": False,
                "show_league_pages": False,
                "espn_credentials": {"home": {"swid_env": "MY_SWID",
                                                 "espn_s2_env": "MY_ESPN_S2"}},
                "leagues": [
                    {"key": "one", "platform": "sleeper", "league_id": "123",
                     "label": "One"},
                    {"key": "two", "platform": "espn", "league_id": "456",
                     "credentials": "home", "display_users": [],
                     "show_league_page": True, "show_all_matchups": True},
                ],
            }))
        self.assertEqual(config.leagues[0].display_users, ("me",))
        self.assertEqual(config.leagues[1].display_users, ())
        self.assertTrue(config.leagues[1].show_league_page)
        self.assertFalse(config.show_all_matchups)
        self.assertTrue(config.leagues[1].show_all_matchups)
        self.assertFalse(config.show_league_pages)
        with patch.dict(os.environ, {"MY_SWID": "{ABC}", "MY_ESPN_S2": "secret"}):
            self.assertEqual(config.credentials["home"].cookies(), {
                "SWID": "{ABC}", "espn_s2": "secret"})

    def test_invalid_config_is_actionable(self):
        changes = (
            ({"default_display_users": ["missing"]}, "unknown users"),
            ({"show_league_pages": "yes"}, "true or false"),
            ({"league_page_seconds": 0}, "positive number"),
            ({"show_all_matchups": "yes"}, "true or false"),
        )
        for change, message in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                value = {
                    "users": {"me": {"sleeper_user_id": "1"}},
                    "leagues": [{"key": "one", "platform": "sleeper",
                                 "league_id": "2"}],
                }
                value.update(change)
                with self.assertRaisesRegex(ValueError, message):
                    load_multi_league_config(self.write_config(folder, value))


if __name__ == "__main__":
    unittest.main()
