import unittest
from unittest.mock import Mock

from league_adapters import EspnLeagueAdapter, selected_owner_ids
from multi_league_config import LeagueConfig, UserIdentity


class EspnAdapterTests(unittest.TestCase):
    def setUp(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "members": [{"id": "{ME}", "displayName": "Christian"}],
            "teams": [
                {"id": 1, "owners": ["{ME}"], "location": "Sunday",
                 "nickname": "Scaries", "logo": "https://logo/1.png",
                 "record": {"overall": {"wins": 2, "losses": 1, "ties": 0}}},
                {"id": 2, "owners": ["{OTHER}"], "name": "Visitors",
                 "record": {"overall": {}}},
            ],
            "schedule": [{"matchupPeriodId": 3,
                          "home": {"teamId": 1, "totalPoints": 0,
                                   "totalPointsLive": 80.5,
                                   "totalProjectedPointsLive": 131.2},
                          "away": {"teamId": 2, "totalPoints": 0,
                                   "pointsByScoringPeriod": {"3": 72.1},
                                   "totalProjectedPointsLive": 119.8}}],
        }
        response.raise_for_status.return_value = None
        session = Mock()
        session.get.return_value = response
        config = LeagueConfig("espn", "espn", "55", "ESPN", ("me",), 2026)
        self.adapter = EspnLeagueAdapter(config, session=session)
        self.session = session

    def test_normalizes_matchups_users_rosters_and_projections(self):
        rows = self.adapter.get_matchups(3)
        self.assertEqual(rows[0]["points"], 80.5)
        self.assertEqual(self.adapter.projections, {"1": 131.2, "2": 119.8})
        self.assertEqual(self.adapter.get_users()[0]["metadata"]["team_name"],
                         "Sunday Scaries")
        self.assertEqual(self.adapter.get_rosters()[0]["settings"]["wins"], 2)
        self.assertEqual(self.session.get.call_args.kwargs["cookies"], None)
        self.assertIn(("view", "mMatchupScore"),
                      self.session.get.call_args.kwargs["params"])

    def test_stable_user_ids_are_platform_specific(self):
        users = {"me": UserIdentity("me", "Christian", "12", "{ME}")}
        self.assertEqual(selected_owner_ids(self.adapter.config, users), {"{ME}"})


if __name__ == "__main__":
    unittest.main()
