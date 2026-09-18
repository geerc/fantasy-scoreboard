"""Estimate live final fantasy scores from Sleeper projections and ESPN clocks."""

import logging
import math
from queue import Empty, Queue
from threading import Event, Thread

import requests
from touchdowns import team_code

SLEEPER = "https://api.sleeper.app/v1"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
LOG = logging.getLogger("fantasy_led.projections")


def league_median(totals):
    """Return the midpoint of the league's two middle team totals."""
    values = sorted(float(value) for value in totals.values())
    if len(values) < 2:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def get_json(url, **params):
    response = requests.get(url, params=params or None, timeout=10)
    response.raise_for_status()
    return response.json()


def clock_seconds(clock):
    try:
        minutes, seconds = str(clock).split(":", 1)
        return max(0, int(minutes) * 60 + int(seconds))
    except (TypeError, ValueError):
        return 0


def remaining_fraction(game):
    """Return the regulation-game fraction remaining for a normalized status."""
    if not game:
        return None
    state = game.get("state")
    if state == "pre":
        return 1.0
    if state == "post":
        return 0.0
    if state != "in":
        return None
    period = max(1, int(game.get("period") or 1))
    if period > 4:
        return 0.0
    elapsed = (period - 1) * 900 + (900 - clock_seconds(game.get("clock")))
    return min(1.0, max(0.0, (3600 - elapsed) / 3600))


def projected_final(actual, pregame, game):
    """Condition a pregame mean on points scored and regulation time remaining."""
    actual = float(actual or 0)
    pregame = float(pregame or 0)
    remaining = remaining_fraction(game)
    if remaining is None:
        return max(actual, pregame)
    if remaining == 1:
        return pregame
    if remaining == 0:
        return actual
    return actual + pregame * remaining


def projection_field(scoring_settings):
    receptions = float((scoring_settings or {}).get("rec", 0) or 0)
    if receptions >= 0.75:
        return "pts_ppr"
    if receptions >= 0.25:
        return "pts_half_ppr"
    return "pts_std"


def calculate_team_projections(matchups, players, projections, team_games,
                               scoring_settings):
    return calculate_team_outlooks(
        matchups, players, projections, team_games, scoring_settings)[0]


POSITION_VOLATILITY = {
    "QB": .45, "RB": .65, "WR": .75, "TE": .75, "K": .65, "DEF": .80,
}


def calculate_team_outlooks(matchups, players, projections, team_games,
                            scoring_settings):
    """Return projected totals and remaining-score standard deviations."""
    field = projection_field(scoring_settings)
    totals = {}
    uncertainties = {}
    for matchup in matchups:
        total = 0.0
        variance = 0.0
        player_points = matchup.get("players_points") or {}
        for player_id in matchup.get("starters") or []:
            player_id = str(player_id)
            player = players.get(player_id) or {}
            actual = float(player_points.get(player_id, 0) or 0)
            pregame = float((projections.get(player_id) or {}).get(field, 0) or 0)
            nfl_team = team_code(str(player.get("team") or "").upper())
            game = team_games.get(nfl_team)
            total += projected_final(actual, pregame, game)
            remaining = remaining_fraction(game)
            remaining = 1.0 if remaining is None else remaining
            if remaining > 0 and pregame > 0:
                position = str(player.get("position") or "").upper()
                volatility = POSITION_VOLATILITY.get(position, .70)
                variance += (pregame * volatility * math.sqrt(remaining)) ** 2
        totals[str(matchup["roster_id"])] = round(total, 2)
        uncertainties[str(matchup["roster_id"])] = round(math.sqrt(variance), 3)
    return totals, uncertainties


class SleeperEspnProjectionSource:
    def __init__(self, league_id):
        self.league_id = league_id
        self.league = None
        self.players = None
        self.projections = {}
        self.projection_context = None

    def poll(self, week):
        if self.league is None:
            self.league = get_json(f"{SLEEPER}/league/{self.league_id}")
        season = str(self.league["season"])
        season_type = self.league.get("season_type", "regular")
        matchups = get_json(f"{SLEEPER}/league/{self.league_id}/matchups/{week}")
        starters = {str(pid) for row in matchups for pid in row.get("starters") or []
                    if pid and str(pid) != "0"}
        if self.players is None:
            self.players = get_json(f"{SLEEPER}/players/nfl")
        context = (season, season_type, week)
        if context != self.projection_context:
            raw = get_json(f"{SLEEPER}/projections/nfl/{season_type}/{season}/{week}")
            if not isinstance(raw, dict):
                raise ValueError("Unexpected Sleeper projections schema")
            self.projections = raw
            self.projection_context = context

        schedule = get_json(
            ESPN_SCOREBOARD, dates=season,
            seasontype={"pre": 1, "regular": 2, "post": 3}.get(season_type, 2),
            week=week, limit=100)
        team_games = {}
        for event in schedule.get("events") or []:
            status = event.get("status") or {}
            normalized = {
                "state": (status.get("type") or {}).get("state"),
                "period": status.get("period"),
                "clock": status.get("displayClock"),
            }
            competitions = event.get("competitions") or []
            for competitor in (competitions[0].get("competitors") if competitions else []) or []:
                abbreviation = (competitor.get("team") or {}).get("abbreviation")
                if abbreviation:
                    team_games[team_code(str(abbreviation).upper())] = normalized
        selected_players = {pid: (self.players or {}).get(pid, {}) for pid in starters}
        totals, uncertainties = calculate_team_outlooks(
            matchups, selected_players, self.projections, team_games,
            self.league.get("scoring_settings") or {})
        return {
            "context": [self.league_id, season, season_type, week],
            "totals": totals,
            "uncertainties": uncertainties,
            "median_enabled": bool(
                (self.league.get("settings") or {}).get("league_average_match")),
        }


class LiveProjectionMonitor:
    def __init__(self, league_id, week, interval=25, source=None):
        self.source = source or SleeperEspnProjectionSource(league_id)
        self.week = week
        self.interval = interval
        self.stop = Event()
        self.results = Queue()
        self.latest = {}
        self.uncertainties = {}
        self.median_enabled = False
        self.version = 0
        self.worker = Thread(target=self._run, name="projection-poller", daemon=True)
        self.worker.start()

    def _run(self):
        while not self.stop.is_set():
            week = self.week
            try:
                self.results.put(self.source.poll(week))
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                LOG.warning("Projection poll failed; retaining prior values: %s", error)
            self.stop.wait(self.interval)

    def totals(self, week):
        self.week = week
        while True:
            try:
                snapshot = self.results.get_nowait()
            except Empty:
                break
            if snapshot["context"][-1] == week:
                self.latest = snapshot["totals"]
                self.uncertainties = snapshot.get("uncertainties", {})
                self.median_enabled = snapshot.get("median_enabled", False)
                self.version += 1
        return self.latest, self.version

    def close(self):
        self.stop.set()


class ReplayProjectionMonitor:
    """Offline monitor with deterministic roster totals supplied by a fixture."""
    def __init__(self, totals=None, median_enabled=False, uncertainties=None):
        self.latest = {str(key): value for key, value in (totals or {}).items()}
        self.uncertainties = {
            str(key): value for key, value in (uncertainties or {}).items()}
        self.median_enabled = median_enabled
        self.delivered = False

    def totals(self, week):
        if not self.delivered:
            self.delivered = True
            return self.latest, 1
        return self.latest, 1

    def close(self):
        pass
