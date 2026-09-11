"""Read-only live polling. Network work stays off the animation thread.

Sleeper's weekly stats endpoint is undocumented. ESPN play-by-play provides per-play yardage, participants, team colors, and the
D/ST subtype missing from Sleeper's aggregate def_td counter. Failure of either
feed leaves its baseline untouched rather than fabricating touchdowns.
"""

import logging
from queue import Queue, Empty
from threading import Event, Thread

import requests

from touchdowns import TouchdownDetector, team_code

LOG = logging.getLogger("fantasy_led.touchdowns")
SLEEPER = "https://api.sleeper.app/v1"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"


def get_json(url, **params):
    response = requests.get(url, params=params or None, timeout=10)
    response.raise_for_status()
    return response.json()


class SleeperTouchdownSource:
    def __init__(self, league_id):
        self.league_id = league_id
        self.league = None
        self.players = None
        self.roster_names = None

    def poll(self, week):
        if self.league is None:
            self.league = get_json(f"{SLEEPER}/league/{self.league_id}")
        season = str(self.league["season"])
        season_type = self.league.get("season_type", "regular")
        matchups = get_json(f"{SLEEPER}/league/{self.league_id}/matchups/{week}")
        if self.roster_names is None:
            users = get_json(f"{SLEEPER}/league/{self.league_id}/users")
            rosters = get_json(f"{SLEEPER}/league/{self.league_id}/rosters")
            user_names = {str(user["user_id"]):
                          (user.get("metadata") or {}).get("team_name") or user.get("display_name") or "Unknown Team"
                          for user in users}
            self.roster_names = {str(roster["roster_id"]):
                                 user_names.get(str(roster.get("owner_id")), "Unknown Team")
                                 for roster in rosters}
        fantasy_teams = {}
        for matchup in matchups:
            team_name = self.roster_names.get(str(matchup.get("roster_id")), "Unknown Team")
            for player_id in matchup.get("players", []):
                if player_id and str(player_id) != "0":
                    fantasy_teams[str(player_id)] = team_name
        starters = sorted({str(pid) for m in matchups for pid in m.get("starters", [])
                           if pid and str(pid) != "0"})
        owned_players = sorted({str(pid) for m in matchups for pid in m.get("players", [])
                                if pid and str(pid) != "0"})
        if self.players is None and owned_players:
            # Large documented player catalogue: fetched once per process.
            self.players = get_json(f"{SLEEPER}/players/nfl")
        players = {pid: (self.players or {}).get(pid, {}) for pid in owned_players}
        stats = None
        if starters:
            try:
                raw = get_json(f"{SLEEPER}/stats/nfl/{season_type}/{season}/{week}")
                if not isinstance(raw, dict) or not all(isinstance(v, dict) for v in raw.values()):
                    raise ValueError("Unexpected Sleeper weekly stats schema")
                stats = raw
            except (requests.RequestException, ValueError) as error:
                LOG.warning("Touchdown stats unavailable; preserving baseline: %s", error)
        defenses = {team_code(pid) for pid in starters
                    if players.get(pid, {}).get("position") == "DEF"
                    or (pid.isalpha() and 2 <= len(pid) <= 3)}
        starter_teams = {team_code(info.get("team")) for info in players.values() if info.get("team")} | defenses
        games = []
        team_colors = {}
        play_by_play_ready = False
        if starter_teams:
            try:
                schedule = get_json(f"{ESPN}/scoreboard", dates=season,
                                    seasontype={"pre": 1, "regular": 2, "post": 3}[season_type],
                                    week=week, limit=100)
                if not isinstance(schedule.get("events"), list):
                    raise ValueError("Unexpected ESPN schedule schema")
                for game in schedule["events"]:
                    competitors = game["competitions"][0]["competitors"]
                    team_by_id = {str(c["team"]["id"]): team_code(c["team"]["abbreviation"])
                                  for c in competitors}
                    for c in competitors:
                        color = c["team"].get("color")
                        if color:
                            team_colors[team_code(c["team"]["abbreviation"])] = "#" + color.lstrip("#")
                    teams = set(team_by_id.values())
                    if not teams & starter_teams:
                        continue
                    game_id = str(game["id"])
                    if game.get("status", {}).get("type", {}).get("state") == "pre":
                        games.append({"id": game_id, "plays": []})
                        continue
                    try:
                        summary = get_json(f"{ESPN}/summary", event=game_id)
                        combined = list(summary.get("scoringPlays") or [])
                        drives = summary.get("drives") or {}
                        drive_rows = list(drives.get("previous") or [])
                        if drives.get("current"):
                            drive_rows.append(drives["current"])
                        for drive in drive_rows:
                            combined.extend(drive.get("plays") or [])
                        by_id = {}
                        for raw_play in combined:
                            play = dict(by_id.get(str(raw_play.get("id")), {}))
                            play.update(raw_play)
                            start_team = str((play.get("start") or {}).get("team", {}).get("id", ""))
                            if start_team in team_by_id:
                                play["offenseTeam"] = team_by_id[start_team]
                            if play.get("id"):
                                by_id[str(play["id"])] = play
                        games.append({"id": game_id, "plays": list(by_id.values())})
                        play_by_play_ready = True
                    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                        LOG.warning("Play-by-play unavailable for game %s: %s", game_id, error)
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                LOG.warning("NFL schedule unavailable; preserving baseline: %s", error)
        return {"context": [self.league_id, season, season_type, week],
                "starters": starters, "owned_players": owned_players, "players": players, "stats": stats, "games": games,
                "team_colors": team_colors, "fantasy_teams": fantasy_teams,
                "play_by_play_ready": play_by_play_ready}


class TouchdownMonitor:
    def __init__(self, league_id, week, interval=30):
        self.source = SleeperTouchdownSource(league_id)
        self.week = week
        self.interval = interval
        self.stop = Event()
        self.results = Queue()
        self.detector = TouchdownDetector()
        self.worker = Thread(target=self._run, name="touchdown-poller", daemon=True)
        self.worker.start()

    def _run(self):
        while not self.stop.is_set():
            week = self.week
            try:
                self.results.put(self.source.poll(week))
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                LOG.warning("Touchdown poll failed; keeping previous state: %s", error)
            self.stop.wait(self.interval)

    def events(self, week, now):
        self.week = week
        events = []
        while True:
            try:
                snapshot = self.results.get_nowait()
            except Empty:
                break
            if snapshot["context"][-1] == week:
                events.extend(self.detector.observe(snapshot))
        return events

    def close(self):
        self.stop.set()


def create_touchdown_monitor(league_id, week, interval=30):
    return TouchdownMonitor(league_id, week, interval)
