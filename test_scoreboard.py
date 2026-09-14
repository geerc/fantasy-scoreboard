"""Offline emulator development harness using saved Sleeper responses."""

import argparse
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import main as scoreboard
from layout_config import (add_layout_arguments, resolve_layout,
                           add_touchdown_arguments, resolve_touchdown_settings)
from touchdowns import ReplayTouchdownMonitor
from live_projections import ReplayProjectionMonitor

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_FIXTURE = PROJECT_DIR / "fixtures" / "sleeper_2025_week8.json"


def load_fixture(path):
    with Path(path).open(encoding="utf-8") as stream:
        fixture = json.load(stream)
    for key in ("league_id", "season", "week", "season_type", "matchups", "users", "rosters"):
        if key not in fixture:
            raise ValueError(f"Fixture is missing {key!r}")
    if type(fixture["week"]) is not int or fixture["week"] < 1:
        raise ValueError("Fixture week must be a positive integer")
    roster_ids = {roster["roster_id"] for roster in fixture["rosters"]}
    groups = Counter()
    for matchup in fixture["matchups"]:
        if matchup["roster_id"] not in roster_ids:
            raise ValueError(f"Unknown roster {matchup['roster_id']}")
        if not isinstance(matchup["points"], (int, float)):
            raise ValueError("Matchup points must be numeric")
        groups[matchup["matchup_id"]] += 1
    if any(key is None or count != 2 for key, count in groups.items()):
        raise ValueError("Each matchup must have an ID and exactly two teams")
    return fixture


class FixtureLeague:
    """The League methods used by main.py, backed by editable JSON."""

    def __init__(self, fixture):
        self.fixture = deepcopy(fixture)

    def get_matchups(self, week):
        if week != self.fixture["week"]:
            raise ValueError(f"This fixture only contains week {self.fixture['week']}")
        return deepcopy(self.fixture["matchups"])

    def get_users(self):
        users = deepcopy(self.fixture["users"])
        for user in users:
            user["metadata"] = user.get("metadata") or {}
            # Reuse local logos (or default.jpg); never download avatars.
            user["metadata"].pop("avatar", None)
        return users

    def get_rosters(self):
        return deepcopy(self.fixture["rosters"])


def run_replay(fixture, rotation_interval=5, data_refresh_interval=60, layout=None, config=None,
               touchdown_duration=None, touchdown_poll_interval=None, touchdown_scenario=None):
    """Run production rendering with isolated inputs and no HTTP access."""
    argv = [
        str(PROJECT_DIR / "main.py"), "--emulator",
        "--league-id", fixture["league_id"],
        "--week", str(fixture["week"]),
        "--rotation-interval", str(rotation_interval),
        "--data-refresh-interval", str(data_refresh_interval),
    ]
    if layout is not None:
        argv.extend(["--layout", layout])
    if config is not None:
        argv.extend(["--config", str(Path(config).resolve())])
    if touchdown_duration is not None:
        argv.extend(["--touchdown-duration", str(touchdown_duration)])
    if touchdown_poll_interval is not None:
        argv.extend(["--touchdown-poll-interval", str(touchdown_poll_interval)])
    previous_dir = Path.cwd()
    try:
        os.chdir(PROJECT_DIR)
        with patch.object(sys, "argv", argv), \
                patch.object(scoreboard, "League", return_value=FixtureLeague(fixture)), \
                patch.object(scoreboard, "create_touchdown_monitor",
                             return_value=ReplayTouchdownMonitor(touchdown_scenario)), \
                patch.object(scoreboard, "LiveProjectionMonitor",
                             return_value=ReplayProjectionMonitor(
                                 fixture.get("live_projections"))), \
                patch.object(scoreboard, "get_current_nfl_state",
                             return_value=(fixture["week"], fixture["season_type"])), \
                patch("requests.sessions.Session.request",
                      side_effect=RuntimeError("HTTP is disabled in offline replay")):
            scoreboard.main()
    finally:
        os.chdir(previous_dir)


def positive_seconds(value):
    seconds = int(value)
    if seconds < 1:
        raise argparse.ArgumentTypeError("interval must be at least 1 second")
    return seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE,
                        help="Editable Sleeper JSON fixture")
    parser.add_argument("--rotation-interval", type=positive_seconds, default=5)
    parser.add_argument("--data-refresh-interval", type=positive_seconds, default=60)
    parser.add_argument("--check", action="store_true",
                        help="Validate the fixture without launching the emulator")
    add_layout_arguments(parser)
    add_touchdown_arguments(parser)
    scenarios = parser.add_mutually_exclusive_group()
    scenarios.add_argument("--touchdown-demo", action="store_true",
                           help="Replay synthetic starter touchdowns, exclusions, and queued D/ST events")
    scenarios.add_argument("--touchdown-scenario", type=Path,
                           help="Custom time-indexed touchdown JSON scenario")
    args = parser.parse_args()
    try:
        fixture = load_fixture(args.fixture)
        layout = resolve_layout(args.layout, args.config)
        duration, poll_interval = resolve_touchdown_settings(
            args.touchdown_duration, args.touchdown_poll_interval, args.config)
        scenario = None
        scenario_path = args.touchdown_scenario
        if args.touchdown_demo:
            scenario_path = PROJECT_DIR / "fixtures" / "touchdown_demo.json"
        if scenario_path:
            with scenario_path.open(encoding="utf-8") as stream:
                scenario = json.load(stream)
            snapshots = scenario["snapshots"]
            if not snapshots or snapshots[0]["at_seconds"] != 0:
                raise ValueError("Touchdown scenario must begin with a baseline at 0 seconds")
            previous = -1
            for entry in snapshots:
                if entry["at_seconds"] < previous:
                    raise ValueError("Touchdown snapshots must be in time order")
                previous = entry["at_seconds"]
                if entry["snapshot"]["context"][-1] != fixture["week"]:
                    raise ValueError("Touchdown scenario and scoreboard fixture weeks must match")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(f"Offline replay: {fixture['season']} Week {fixture['week']} | "
          f"league {fixture['league_id']} | {len(fixture['matchups']) // 2} matchups")
    if args.check:
        print("Fixture validation passed. No network or emulator started.")
        return
    print("Stop any existing emulator on port 8888 before launching this replay.")
    run_replay(fixture, args.rotation_interval, args.data_refresh_interval,
               layout=layout, config=args.config, touchdown_duration=duration,
               touchdown_poll_interval=poll_interval, touchdown_scenario=scenario)


if __name__ == "__main__":
    main()
