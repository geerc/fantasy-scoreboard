import unittest

from multi_league_config import UserIdentity
from multi_league_events import CrossLeagueCelebrations, real_play_key
from touchdowns import Touchdown


def event(league, team, owner, event_id="league:2026:regular:1:game:123:TOUCHDOWN"):
    return Touchdown(event_id, "p1", "Player", "TOUCHDOWN", 52, "RUSH",
                     "#123456", team, owner, league)


class MultiLeagueCelebrationTests(unittest.TestCase):
    def setUp(self):
        self.users = {"me": UserIdentity("me", "Christian", "sleep-me", "{ME}"),
                      "other": UserIdentity("other", "Other", "sleep-other", "{OTHER}")}

    def test_one_occurrence_uses_team_and_deduplicates_later_poll(self):
        merge = CrossLeagueCelebrations(self.users)
        original = event("one", "Sunday Scaries", "sleep-me")
        self.assertEqual(merge.merge([original])[0].fantasy_team, "Sunday Scaries")
        self.assertEqual(merge.merge([original]), [])

    def test_same_user_multiple_leagues_uses_user_label(self):
        merge = CrossLeagueCelebrations(self.users)
        copies = [event("one", "Team One", "sleep-me"),
                  event("two", "Team Two", "{ME}")]
        result = merge.merge(copies)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].fantasy_team, "Christian")

    def test_different_users_remove_attribution(self):
        merge = CrossLeagueCelebrations(self.users)
        copies = [event("one", "Team One", "sleep-me"),
                  event("two", "Team Two", "{OTHER}")]
        self.assertIsNone(merge.merge(copies)[0].fantasy_team)

    def test_play_key_ignores_league_context(self):
        one = event("one", "A", "sleep-me", "one:2026:regular:1:401:987:TOUCHDOWN")
        two = event("two", "B", "{ME}", "espn:two:2026:1:401:987:TOUCHDOWN")
        self.assertEqual(real_play_key(one), real_play_key(two))

    def test_configured_user_ownership_precedes_league_priority(self):
        merge = CrossLeagueCelebrations(self.users, ("preferred", "mine"))
        copies = [event("preferred", "Someone Else", "not-me"),
                  event("mine", "My Team", "sleep-me")]
        self.assertEqual(merge.merge(copies)[0].fantasy_team, "My Team")

    def test_hierarchy_selects_team_when_user_owns_player_multiple_times(self):
        merge = CrossLeagueCelebrations(self.users, ("second", "first"))
        copies = [event("first", "Lower Team", "sleep-me"),
                  event("second", "Priority Team", "{ME}")]
        self.assertEqual(merge.merge(copies)[0].fantasy_team, "Priority Team")

    def test_hierarchy_applies_to_non_user_occurrences(self):
        merge = CrossLeagueCelebrations(self.users, ("second", "first"))
        copies = [event("first", "Lower Team", "stranger-one"),
                  event("second", "Priority Team", "stranger-two")]
        self.assertEqual(merge.merge(copies)[0].fantasy_team, "Priority Team")


if __name__ == "__main__":
    unittest.main()
