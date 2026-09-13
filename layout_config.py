"""Shared layout selection for the live board and offline replay."""

import json
from pathlib import Path

LAYOUTS = ("classic", "diagonal")
DEFAULT_CONFIG = Path(__file__).resolve().with_name("board_config.json")


def add_layout_arguments(parser):
    parser.add_argument("--layout", choices=LAYOUTS,
                        help="Board layout; overrides the JSON config")
    parser.add_argument("--config", type=Path,
                        help="Board JSON config (default: board_config.json beside main.py)")


def resolve_layout(layout=None, config=None):
    path = Path(config) if config is not None else DEFAULT_CONFIG
    settings = {}
    if config is not None or path.exists():
        with path.open(encoding="utf-8") as stream:
            settings = json.load(stream)
        if not isinstance(settings, dict):
            raise ValueError("Board config must be a JSON object")
    selected = layout if layout is not None else settings.get("layout", "classic")
    if selected not in LAYOUTS:
        raise ValueError(f"Invalid layout {selected!r}; choose classic or diagonal")
    return selected


def add_touchdown_arguments(parser):
    parser.add_argument("--touchdown-duration", type=float,
                        help="Total celebration seconds; overrides touchdown_duration_seconds")
    parser.add_argument("--touchdown-poll-interval", type=float,
                        help="Seconds between live touchdown polls (default: 30)")


def resolve_touchdown_settings(duration=None, poll_interval=None, config=None):
    import math
    path = Path(config) if config is not None else DEFAULT_CONFIG
    settings = {}
    if config is not None or path.exists():
        with path.open(encoding="utf-8") as stream:
            settings = json.load(stream)
        if not isinstance(settings, dict):
            raise ValueError("Board config must be a JSON object")
    duration = duration if duration is not None else settings.get("touchdown_duration_seconds", 10)
    poll_interval = poll_interval if poll_interval is not None else settings.get("touchdown_poll_interval_seconds", 30)
    for label, value in (("touchdown duration", duration), ("touchdown poll interval", poll_interval)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label} must be a finite positive number")
    return float(duration), float(poll_interval)
