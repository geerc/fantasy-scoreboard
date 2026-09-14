"""Touchdown detection and interrupt playback, independent of display hardware."""

from collections import deque
from dataclasses import dataclass
import math
import re


def team_code(value):
    return {"WSH": "WAS", "LA": "LAR"}.get(value, value)


def dst_kind(play):
    """Classify scoring plays, never aggregate D/ST points or offensive TDs."""
    if ((play.get("scoringType") or {}).get("name") != "touchdown"
            and not play.get("scoringPlay")):
        return None
    text = (play.get("type") or {}).get("text", "").lower()
    if "interception" in text:
        return "INT TOUCHDOWN"
    if "fumble" in text and "recovery (own)" not in text:
        return "FUM TOUCHDOWN"
    if any(term in text for term in ("punt", "kickoff", "kick return", "blocked", "field goal return")):
        return "RETURN TOUCHDOWN"
    return None


@dataclass(frozen=True)
class Touchdown:
    event_id: str
    player_id: str
    name: str
    kind: str
    yards: int = None
    play_type: str = None
    team_color: str = None
    fantasy_team: str = None
    fantasy_owner: str = None
    fantasy_league: str = None


def _normalized_name(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def play_actor(play, starters, players, role_override=None):
    """Map ESPN rusher/receiver data to a Sleeper starter."""
    type_text = (play.get("type") or {}).get("text", "")
    role = role_override or ("receiver" if type_text in ("Pass Reception", "Passing Touchdown")
                            else "rusher" if type_text in ("Rush", "Rushing Touchdown") else None)
    if role is None:
        return None, None
    offense_team = team_code(play.get("offenseTeam"))
    candidates = [pid for pid in starters if team_code(players.get(pid, {}).get("team")) == offense_team]
    candidates = candidates or list(starters)
    participant = next((p for p in play.get("participants") or [] if p.get("type") == role), None)
    full_name = ((participant or {}).get("athlete") or {}).get("fullName")
    if full_name:
        target = _normalized_name(full_name)
        pid = next((pid for pid in candidates
                    if _normalized_name(players.get(pid, {}).get("full_name")) == target), None)
        if pid:
            return pid, role
    text = play.get("text", "")
    if role == "receiver":
        pattern = r"\bto ([A-Z]\.[A-Za-z\x27-]+)"
    elif role == "passer":
        pattern = r"(?:^|\) )\s*([A-Z]\.[A-Za-z\x27-]+) pass"
    else:
        pattern = r"(?:^|\) )\s*([A-Z]\.[A-Za-z\x27-]+)"
    match = re.search(pattern, text)
    if not match:
        return None, role
    short = match.group(1).replace(".", "").lower()
    pid = next((pid for pid in candidates if (lambda parts: parts and
                (parts[0][0] + parts[-1]).lower() == short)(
                    (players.get(pid, {}).get("full_name") or "").split())), None)
    return pid, role


class TouchdownDetector:
    """Baseline first successful observations; emit only newly increased counts/IDs.

    Offensive counts use a high-water mark so a correction and restoration do
    not replay a TD. D/ST uses stable scoring-play IDs, not def_td aggregates.
    """

    def __init__(self):
        self.context = None
        self.counts = {}
        self.offense_ready = False
        self.starters = set()
        self.games = {}
        self.dst_starters = set()

    def observe(self, snapshot):
        context = tuple(snapshot["context"])
        if context != self.context:
            self.__init__()
            self.context = context
        starters = {str(pid) for pid in snapshot["starters"] if str(pid) not in ("0", "None", "")}
        players = snapshot.get("players", {})
        defenses = {pid for pid in starters if players.get(pid, {}).get("position") == "DEF"
                    or (not players.get(pid) and pid.isalpha() and 2 <= len(pid) <= 3)}
        events = []
        stats = snapshot.get("stats")
        play_by_play_ready = snapshot.get("play_by_play_ready", False)
        if stats is not None and not play_by_play_ready:
            for pid in sorted(starters - defenses):
                row = stats.get(pid)
                for field, kind in (("rush_td", "RUSHING TD"), ("rec_td", "RECEIVING TD")):
                    key = (pid, field)
                    # Missing rows on a later poll must not reset a known count.
                    if row is None and key in self.counts:
                        continue
                    count = (row or {}).get(field, 0)
                    if not isinstance(count, (int, float)) or not math.isfinite(count) or count < 0 or int(count) != count:
                        continue
                    count = int(count)
                    previous = self.counts.get(key, 0)
                    if self.offense_ready and pid in self.starters:
                        for ordinal in range(previous + 1, count + 1):
                            info = players.get(pid, {})
                            name = info.get("full_name") or " ".join(filter(None, (
                                info.get("first_name"), info.get("last_name")))) or pid
                            events.append(Touchdown(
                                f"{context}:{pid}:{field}:{ordinal}", pid, name, kind,
                                team_color=snapshot.get("team_colors", {}).get(
                                    team_code(info.get("team"))),
                                fantasy_team=snapshot.get("fantasy_teams", {}).get(pid),
                                fantasy_owner=snapshot.get("fantasy_owners", {}).get(pid),
                                fantasy_league=snapshot.get("fantasy_league")))
                    self.counts[key] = max(previous, count)
            self.starters = starters
            self.offense_ready = True

        # Only successfully fetched games appear here; failures preserve state.
        for game in snapshot.get("games", []):
            game_id = str(game["id"])
            seen = self.games.get(game_id)
            current_ids = {str(p["id"]) for p in game["plays"] if p.get("id")}
            for play in game["plays"]:
                play_id = str(play.get("id", ""))
                is_new = bool(play_id and seen is not None and play_id not in seen)
                actor, role = play_actor(play, starters - defenses, players)
                scoring = bool(play.get("scoringPlay"))
                if scoring and role == "receiver" and actor is None:
                    passer, _ = play_actor(play, starters - defenses, players, "passer")
                    if passer:
                        actor, role = passer, "passer"
                yards = play.get("statYardage")
                eligible = (role is not None and isinstance(yards, (int, float)) and yards >= 0
                            and (scoring or yards >= 50))
                if is_new and eligible and actor is None and not play.get("participants"):
                    # ESPN sometimes adds participants after the play first appears.
                    current_ids.discard(play_id)
                if is_new and actor and eligible:
                    info = players.get(actor, {})
                    name = info.get("full_name") or actor
                    color = snapshot.get("team_colors", {}).get(team_code(info.get("team")))
                    kind = "TOUCHDOWN" if scoring else "BIG PLAY"
                    events.append(Touchdown(f"{context}:{game_id}:{play_id}:{kind}", actor, name, kind,
                                            int(yards), "RECEPTION" if role == "receiver" else "PASS" if role == "passer" else "RUSH", color,
                                            snapshot.get("fantasy_teams", {}).get(actor),
                                            snapshot.get("fantasy_owners", {}).get(actor),
                                            snapshot.get("fantasy_league")))

                pid = next((d for d in defenses if team_code(
                            players.get(d, {}).get("team") or d) ==
                            team_code((play.get("team") or {}).get("abbreviation"))), None)
                kind = dst_kind(play)
                if (pid and kind and play_id and seen is not None and play_id not in seen
                        and pid in self.dst_starters):
                    events.append(Touchdown(f"{context}:{game_id}:{play_id}", pid, f"{pid} D/ST", kind,
                                            int(play.get("statYardage") or 0), None,
                                            snapshot.get("team_colors", {}).get(team_code(pid)),
                                            snapshot.get("fantasy_teams", {}).get(pid),
                                            snapshot.get("fantasy_owners", {}).get(pid),
                                            snapshot.get("fantasy_league")))
            self.games[game_id] = (seen or set()) | current_ids
        self.dst_starters = defenses
        return events


class CelebrationQueue:
    def __init__(self, duration=5):
        self.duration = duration
        self.pending = deque()
        self.active = None
        self.started_at = None

    def step(self, now, events=()):
        self.pending.extend(events)
        if self.active is not None and now - self.started_at >= self.duration:
            self.active = None
        if self.active is None and self.pending:
            self.active = self.pending.popleft()
            self.started_at = now
        if self.active is None:
            return None
        return self.active, now - self.started_at


class ReplayTouchdownMonitor:
    """Time-indexed synthetic snapshots exercise exactly the live detector."""

    def __init__(self, scenario=None):
        self.snapshots = (scenario or {}).get("snapshots", [])
        self.index = 0
        self.started_at = None
        self.detector = TouchdownDetector()

    def events(self, week, now):
        if self.started_at is None:
            self.started_at = now
        events = []
        while self.index < len(self.snapshots):
            entry = self.snapshots[self.index]
            if entry["at_seconds"] > now - self.started_at:
                break
            if entry["snapshot"]["context"][-1] == week:
                events.extend(self.detector.observe(entry["snapshot"]))
            self.index += 1
        return events

    def close(self):
        pass
