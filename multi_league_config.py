"""Validated configuration for optional multi-league display mode."""

from dataclasses import dataclass
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class UserIdentity:
    key: str
    label: str
    sleeper_user_id: str = None
    espn_owner_id: str = None


@dataclass(frozen=True)
class EspnCredentials:
    key: str
    swid_env: str
    espn_s2_env: str

    def cookies(self):
        swid = os.getenv(self.swid_env)
        espn_s2 = os.getenv(self.espn_s2_env)
        if not swid or not espn_s2:
            raise ValueError(
                f"ESPN credential profile {self.key!r} requires environment "
                f"variables {self.swid_env} and {self.espn_s2_env}")
        return {"SWID": swid, "espn_s2": espn_s2}


@dataclass(frozen=True)
class LeagueConfig:
    key: str
    platform: str
    league_id: str
    label: str
    display_users: tuple
    season: int = None
    credentials: str = None
    show_league_page: bool = None
    show_all_matchups: bool = None


@dataclass(frozen=True)
class MultiLeagueConfig:
    users: dict
    leagues: tuple
    credentials: dict
    show_league_pages: bool = True
    league_page_seconds: float = 5.0
    show_all_matchups: bool = None


def _string(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def load_multi_league_config(path):
    """Return None for legacy configs; otherwise validate multi-league settings."""
    if path is None:
        return None
    with Path(path).open(encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError("Board config must be a JSON object")
    if "leagues" not in raw:
        return None

    raw_users = raw.get("users", {})
    if not isinstance(raw_users, dict):
        raise ValueError("users must be an object keyed by a readable user name")
    users = {}
    for key, value in raw_users.items():
        key = _string(key, "user key")
        if not isinstance(value, dict):
            raise ValueError(f"users.{key} must be an object")
        sleeper_id = value.get("sleeper_user_id")
        espn_id = value.get("espn_owner_id")
        if sleeper_id is None and espn_id is None:
            raise ValueError(f"users.{key} needs a Sleeper or ESPN stable ID")
        users[key] = UserIdentity(
            key, _string(value.get("label", key), f"users.{key}.label"),
            str(sleeper_id) if sleeper_id is not None else None,
            str(espn_id) if espn_id is not None else None)

    raw_credentials = raw.get("espn_credentials", {})
    if not isinstance(raw_credentials, dict):
        raise ValueError("espn_credentials must be an object")
    credentials = {}
    for key, value in raw_credentials.items():
        if not isinstance(value, dict):
            raise ValueError(f"espn_credentials.{key} must be an object")
        credentials[key] = EspnCredentials(
            key,
            _string(value.get("swid_env"), f"espn_credentials.{key}.swid_env"),
            _string(value.get("espn_s2_env"), f"espn_credentials.{key}.espn_s2_env"))

    default_users = raw.get("default_display_users")
    if default_users is not None and not isinstance(default_users, list):
        raise ValueError("default_display_users must be a list")
    show_all = raw.get("show_all_matchups")
    if show_all is not None and not isinstance(show_all, bool):
        raise ValueError("show_all_matchups must be true or false")
    raw_leagues = raw.get("leagues")
    if not isinstance(raw_leagues, list) or not raw_leagues:
        raise ValueError("leagues must be a non-empty list")
    leagues = []
    keys = set()
    for index, value in enumerate(raw_leagues):
        path_name = f"leagues[{index}]"
        if not isinstance(value, dict):
            raise ValueError(f"{path_name} must be an object")
        key = _string(value.get("key"), f"{path_name}.key")
        if key in keys:
            raise ValueError(f"Duplicate league key {key!r}")
        keys.add(key)
        platform = _string(value.get("platform"), f"{path_name}.platform").lower()
        if platform not in ("sleeper", "espn"):
            raise ValueError(f"{path_name}.platform must be sleeper or espn")
        selected_users = value.get("display_users", default_users)
        if selected_users is not None and not isinstance(selected_users, list):
            raise ValueError(f"{path_name}.display_users must be a list")
        selected_users = tuple(selected_users or ())
        unknown = set(selected_users) - set(users)
        if unknown:
            raise ValueError(f"{path_name} references unknown users: {sorted(unknown)}")
        id_field = "sleeper_user_id" if platform == "sleeper" else "espn_owner_id"
        missing_ids = [key for key in selected_users if not getattr(users[key], id_field)]
        if missing_ids:
            raise ValueError(
                f"{path_name} display users need a {platform} stable ID: {missing_ids}")
        credential_key = value.get("credentials")
        if credential_key is not None and credential_key not in credentials:
            raise ValueError(f"{path_name} references unknown ESPN credentials")
        season = value.get("season")
        if season is not None and (isinstance(season, bool) or not isinstance(season, int)):
            raise ValueError(f"{path_name}.season must be an integer")
        league_page = value.get("show_league_page")
        if league_page is not None and not isinstance(league_page, bool):
            raise ValueError(f"{path_name}.show_league_page must be true or false")
        league_show_all = value.get("show_all_matchups")
        if league_show_all is not None and not isinstance(league_show_all, bool):
            raise ValueError(f"{path_name}.show_all_matchups must be true or false")
        effective_show_all = league_show_all if league_show_all is not None else show_all
        if effective_show_all is False and not selected_users:
            raise ValueError(
                f"{path_name} needs display_users when show_all_matchups is false")
        leagues.append(LeagueConfig(
            key, platform, _string(value.get("league_id"), f"{path_name}.league_id"),
            _string(value.get("label", key), f"{path_name}.label"),
            selected_users, season, credential_key, league_page, league_show_all))

    show_pages = raw.get("show_league_pages", True)
    if not isinstance(show_pages, bool):
        raise ValueError("show_league_pages must be true or false")
    page_seconds = raw.get("league_page_seconds", 5)
    if (isinstance(page_seconds, bool) or not isinstance(page_seconds, (int, float))
            or page_seconds <= 0):
        raise ValueError("league_page_seconds must be a positive number")
    return MultiLeagueConfig(
        users, tuple(leagues), credentials, show_pages, float(page_seconds), show_all)
