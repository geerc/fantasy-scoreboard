"""Deterministic Monte Carlo estimates for fantasy matchup win probability."""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random

from layout_config import DEFAULT_CONFIG


@dataclass(frozen=True)
class WinProbabilitySettings:
    enabled: bool = False
    display: str = "alternate"
    interval_seconds: float = 3.0
    simulations: int = 5000


def add_win_probability_arguments(parser):
    parser.add_argument(
        "--win-probability", action=argparse_bool(), default=None,
        help="Show Monte Carlo win probability; overrides show_win_probability")
    parser.add_argument(
        "--win-probability-simulations", type=int,
        help="Monte Carlo trials per projection update (default: 5000)")


def argparse_bool():
    """Return a BooleanOptionalAction without importing argparse at module load."""
    import argparse
    return argparse.BooleanOptionalAction


def resolve_win_probability_settings(enabled=None, simulations=None, config=None):
    path = Path(config) if config is not None else DEFAULT_CONFIG
    values = {}
    if config is not None or path.exists():
        with path.open(encoding="utf-8") as stream:
            values = json.load(stream)
        if not isinstance(values, dict):
            raise ValueError("Board config must be a JSON object")

    enabled = values.get("show_win_probability", False) if enabled is None else enabled
    simulations = (values.get("win_probability_simulations", 5000)
                   if simulations is None else simulations)
    display = values.get("win_probability_display", "alternate")
    interval = values.get("win_probability_interval_seconds", 3)
    if not isinstance(enabled, bool):
        raise ValueError("show_win_probability must be true or false")
    if display not in ("alternate", "probability"):
        raise ValueError("win_probability_display must be alternate or probability")
    if (isinstance(interval, bool) or not isinstance(interval, (int, float)) or
            not math.isfinite(interval) or interval <= 0):
        raise ValueError("win_probability_interval_seconds must be a finite positive number")
    if (isinstance(simulations, bool) or not isinstance(simulations, int) or
            not 100 <= simulations <= 100000):
        raise ValueError("win_probability_simulations must be an integer from 100 to 100000")
    return WinProbabilitySettings(enabled, display, float(interval), simulations)


def estimate_uncertainty(actual, projected):
    """Estimate remaining team-score standard deviation from live projections."""
    actual = float(actual or 0)
    projected = max(actual, float(projected if projected is not None else actual))
    remaining = projected - actual
    if remaining <= 0.05:
        return 0.0
    return min(25.0, max(1.0, 1.7 * math.sqrt(remaining)))


def simulate_matchup(team1, team2, simulations=5000, uncertainties=None):
    """Return deterministic (team 1, team 2) win percentages, splitting ties."""
    uncertainties = uncertainties or {}

    def inputs(team):
        actual = float(team.get("points") or 0)
        mean = max(actual, float(team.get("projection")
                                 if team.get("projection") is not None else actual))
        roster_id = str(team.get("roster_id", ""))
        sigma = uncertainties.get(roster_id)
        if sigma is None:
            sigma = estimate_uncertainty(actual, mean)
        return actual, mean, max(0.0, float(sigma))

    first = inputs(team1)
    second = inputs(team2)
    seed_values = [round(value, 4) for value in first + second]
    seed_values.extend((str(team1.get("roster_id", "")),
                        str(team2.get("roster_id", "")), simulations))
    seed = int.from_bytes(hashlib.sha256(
        json.dumps(seed_values, separators=(",", ":")).encode()).digest()[:8], "big")
    rng = random.Random(seed)
    first_wins = 0.0
    for _ in range(simulations):
        score1 = max(first[0], rng.gauss(first[1], first[2])) if first[2] else first[1]
        score2 = max(second[0], rng.gauss(second[1], second[2])) if second[2] else second[1]
        if score1 > score2:
            first_wins += 1
        elif score1 == score2:
            first_wins += 0.5
    first_probability = round(first_wins * 100 / simulations, 1)
    return first_probability, round(100.0 - first_probability, 1)


def update_matchup_probabilities(matchups, simulations=5000, uncertainties=None):
    """Attach win probabilities to each normalized matchup in place."""
    for matchup in matchups:
        team1, team2 = matchup["team1"], matchup["team2"]
        first, second = simulate_matchup(team1, team2, simulations, uncertainties)
        team1["win_probability"] = first
        team2["win_probability"] = second
