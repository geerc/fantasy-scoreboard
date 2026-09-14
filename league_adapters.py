"""Normalize Sleeper and ESPN fantasy leagues for the board renderer."""

from copy import deepcopy
from datetime import datetime

import requests
from sleeper_wrapper import League


ESPN_FANTASY = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"


class SleeperLeagueAdapter:
    platform = "sleeper"

    def __init__(self, config):
        self.config = config
        self.client = League(config.league_id)

    def get_matchups(self, week):
        return self.client.get_matchups(week)

    def get_users(self):
        return self.client.get_users()

    def get_rosters(self):
        return self.client.get_rosters()


class EspnLeagueAdapter:
    """Expose the subset of Sleeper's wrapper interface used by main.py."""

    platform = "espn"

    def __init__(self, config, credential_profiles=None, session=None):
        self.config = config
        self.credentials = credential_profiles or {}
        self.session = session or requests.Session()
        self.snapshot = None
        self.snapshot_week = None
        self.projections = {}

    def _cookies(self):
        if not self.config.credentials:
            return None
        return self.credentials[self.config.credentials].cookies()

    def _load(self, week):
        if self.snapshot is not None and self.snapshot_week == week:
            return
        season = self.config.season or datetime.now().year
        url = (f"{ESPN_FANTASY}/seasons/{season}/segments/0/leagues/"
               f"{self.config.league_id}")
        response = self.session.get(
            url, params=[("view", "mTeam"), ("view", "mMatchup"),
                         ("view", "mMatchupScore"), ("view", "mRoster"),
                         ("view", "mSettings")],
            cookies=self._cookies(), timeout=15)
        if response.status_code in (401, 403):
            raise ValueError(
                f"ESPN league {self.config.key!r} is private or its credentials expired")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data.get("teams"), list) or not isinstance(data.get("schedule"), list):
            raise ValueError(f"Unexpected ESPN response for league {self.config.key!r}")
        self.snapshot = data
        self.snapshot_week = week
        self.projections = {}

    @staticmethod
    def _owner(team):
        owners = team.get("owners") or []
        return str(owners[0]) if owners else f"team:{team.get('id')}"

    @staticmethod
    def _team_name(team):
        return (team.get("name") or
                " ".join(filter(None, (team.get("location"), team.get("nickname")))) or
                team.get("abbrev") or "Unknown Team")

    def get_users(self):
        if self.snapshot is None:
            raise RuntimeError("Call get_matchups before get_users")
        members = {str(row.get("id")): row for row in self.snapshot.get("members") or []}
        users = []
        for team in self.snapshot["teams"]:
            owner_id = self._owner(team)
            member = members.get(owner_id, {})
            users.append({
                "user_id": owner_id,
                "display_name": member.get("displayName") or self._team_name(team),
                "avatar": None,
                "metadata": {"team_name": self._team_name(team),
                             "avatar": team.get("logo")},
            })
        return users

    def get_rosters(self):
        if self.snapshot is None:
            raise RuntimeError("Call get_matchups before get_rosters")
        rows = []
        for team in self.snapshot["teams"]:
            record = ((team.get("record") or {}).get("overall") or {})
            rows.append({
                "owner_id": self._owner(team),
                "roster_id": int(team["id"]),
                "settings": {"wins": int(record.get("wins") or 0),
                             "losses": int(record.get("losses") or 0),
                             "ties": int(record.get("ties") or 0)},
            })
        return rows

    @staticmethod
    def _projected(side):
        for key in ("totalProjectedPointsLive", "totalProjectedPoints"):
            value = side.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    @staticmethod
    def _points(side, week):
        live = side.get("totalPointsLive")
        if isinstance(live, (int, float)):
            return float(live)
        by_period = side.get("pointsByScoringPeriod") or {}
        period = by_period.get(str(week), by_period.get(week))
        if isinstance(period, (int, float)):
            return float(period)
        total = side.get("totalPoints")
        return float(total) if isinstance(total, (int, float)) else 0.0

    def get_matchups(self, week):
        # ESPN changes live fields in-place, so each call deliberately refreshes.
        self.snapshot = None
        self._load(week)
        rows = []
        matchup_id = 0
        for matchup in self.snapshot["schedule"]:
            period = matchup.get("matchupPeriodId") or matchup.get("scoringPeriodId")
            if int(period or 0) != int(week):
                continue
            sides = [matchup.get("home"), matchup.get("away")]
            if not all(isinstance(side, dict) and side.get("teamId") for side in sides):
                continue
            matchup_id += 1
            for side in sides:
                team_id = str(side["teamId"])
                projection = self._projected(side)
                if projection is not None:
                    self.projections[team_id] = projection
                rows.append({"matchup_id": matchup_id,
                             "roster_id": int(team_id),
                             "points": self._points(side, week),
                             "projection": projection})
        return deepcopy(rows)


def create_league_adapter(config, credential_profiles=None, session=None):
    if config.platform == "sleeper":
        return SleeperLeagueAdapter(config)
    return EspnLeagueAdapter(config, credential_profiles, session)


def selected_owner_ids(league, users, global_show_all=None):
    """Translate config user keys into platform-specific stable owner IDs."""
    show_all = (league.show_all_matchups if league.show_all_matchups is not None
                else global_show_all)
    # Backward compatibility: an omitted scope with no display users meant all.
    if show_all is True or (show_all is None and not league.display_users):
        return None
    field = "sleeper_user_id" if league.platform == "sleeper" else "espn_owner_id"
    return {getattr(users[key], field) for key in league.display_users
            if getattr(users[key], field)}
