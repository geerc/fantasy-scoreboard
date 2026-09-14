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
ESPN_FANTASY = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"


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
        self.roster_owners = None

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
            self.roster_owners = {str(roster["roster_id"]): str(roster.get("owner_id"))
                                  for roster in rosters}
        fantasy_teams = {}
        fantasy_owners = {}
        for matchup in matchups:
            roster_id = str(matchup.get("roster_id"))
            team_name = self.roster_names.get(roster_id, "Unknown Team")
            for player_id in matchup.get("players", []):
                if player_id and str(player_id) != "0":
                    fantasy_teams[str(player_id)] = team_name
                    fantasy_owners[str(player_id)] = self.roster_owners.get(roster_id)
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
                "fantasy_owners": fantasy_owners, "fantasy_league": self.league_id,
                "play_by_play_ready": play_by_play_ready}


class TouchdownMonitor:
    def __init__(self, league_id, week, interval=30, source=None):
        self.source = source or SleeperTouchdownSource(league_id)
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


class EspnTouchdownSource:
    """Use ESPN fantasy starters with ESPN's NFL play feed."""

    def __init__(self, config, credential_profiles=None):
        self.config = config
        self.credentials = credential_profiles or {}

    def _cookies(self):
        if not self.config.credentials:
            return None
        return self.credentials[self.config.credentials].cookies()

    def poll(self, week):
        from datetime import datetime
        season = self.config.season or datetime.now().year
        url = (f"{ESPN_FANTASY}/seasons/{season}/segments/0/leagues/"
               f"{self.config.league_id}")
        response = requests.get(url, params=[("view", "mTeam"), ("view", "mRoster")],
                                cookies=self._cookies(), timeout=15)
        response.raise_for_status()
        fantasy = response.json()
        fantasy_teams = {}
        fantasy_owners = {}
        players = {}
        starters = set()
        for team in fantasy.get("teams") or []:
            owner = str((team.get("owners") or [f"team:{team.get('id')}"])[0])
            team_name = (team.get("name") or " ".join(filter(None, (
                team.get("location"), team.get("nickname")))) or "Unknown Team")
            entries = ((team.get("roster") or {}).get("entries") or [])
            for entry in entries:
                pool = entry.get("playerPoolEntry") or {}
                player = pool.get("player") or {}
                pid = str(player.get("id") or "")
                if not pid:
                    continue
                players[pid] = {"full_name": player.get("fullName") or player.get("name") or pid,
                                "position": "DEF" if player.get("defaultPositionId") == 16 else None,
                                "pro_team_id": str(player.get("proTeamId") or "")}
                fantasy_teams[pid] = team_name
                fantasy_owners[pid] = owner
                if entry.get("lineupSlotId") not in (20, 21):
                    starters.add(pid)

        schedule = get_json(f"{ESPN}/scoreboard", dates=season, seasontype=2,
                            week=week, limit=100)
        games = []
        team_colors = {}
        for game in schedule.get("events") or []:
            competitors = ((game.get("competitions") or [{}])[0].get("competitors") or [])
            team_by_id = {str(c["team"]["id"]): team_code(c["team"]["abbreviation"])
                          for c in competitors}
            for info in players.values():
                if info.get("pro_team_id") in team_by_id:
                    info["team"] = team_by_id[info["pro_team_id"]]
            for competitor in competitors:
                team = competitor.get("team") or {}
                if team.get("color"):
                    team_colors[team_code(team.get("abbreviation"))] = "#" + team["color"].lstrip("#")
            game_id = str(game.get("id"))
            if game.get("status", {}).get("type", {}).get("state") == "pre":
                games.append({"id": game_id, "plays": []})
                continue
            try:
                summary = get_json(f"{ESPN}/summary", event=game_id)
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                LOG.warning("ESPN play-by-play unavailable for game %s: %s", game_id, error)
                continue
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
                start_id = str((play.get("start") or {}).get("team", {}).get("id", ""))
                if start_id in team_by_id:
                    play["offenseTeam"] = team_by_id[start_id]
                if play.get("id"):
                    by_id[str(play["id"])] = play
            games.append({"id": game_id, "plays": list(by_id.values())})
        return {"context": ["espn", self.config.league_id, season, week],
                "starters": sorted(starters), "owned_players": sorted(players),
                "players": players, "stats": None, "games": games,
                "team_colors": team_colors, "fantasy_teams": fantasy_teams,
                "fantasy_owners": fantasy_owners, "fantasy_league": self.config.key,
                "play_by_play_ready": True}


def create_league_touchdown_monitor(config, credentials, week, interval=30):
    if config.platform == "sleeper":
        source = SleeperTouchdownSource(config.league_id)
    else:
        source = EspnTouchdownSource(config, credentials)
    return TouchdownMonitor(config.league_id, week, interval, source)
