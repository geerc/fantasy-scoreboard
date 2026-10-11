"""Cross-league celebration deduplication and attribution."""

from dataclasses import replace


def real_play_key(event):
    """Drop league context while retaining the stable NFL play identity."""
    parts = event.event_id.split(":")
    if len(parts) >= 3 and parts[-2].isdigit():
        return (parts[-2], parts[-1], event.kind)
    return (event.player_id, event.kind, event.yards, event.play_type,
            parts[-1] if parts else event.event_id)


class CrossLeagueCelebrations:
    """Suppress the same play across leagues and choose one attribution label."""

    def __init__(self, users, league_priority=()):
        self.users = users
        self.league_priority = tuple(league_priority)
        self.priority_index = {
            league: index for index, league in enumerate(self.league_priority)}
        self.owner_keys = {}
        for key, user in users.items():
            for owner_id in (user.sleeper_user_id, user.espn_owner_id):
                if owner_id:
                    self.owner_keys[str(owner_id)] = key
        self.seen = set()

    def merge(self, events):
        grouped = {}
        for event in events:
            grouped.setdefault(real_play_key(event), []).append(event)
        output = []
        for key, copies in grouped.items():
            if key in self.seen:
                continue
            self.seen.add(key)
            first = copies[0]
            if self.league_priority:
                owned = [event for event in copies
                         if self.owner_keys.get(str(event.fantasy_owner))]
                candidates = owned or copies
                selected = min(
                    enumerate(candidates),
                    key=lambda row: (
                        self.priority_index.get(
                            row[1].fantasy_league, len(self.priority_index)),
                        row[0]))[1]
                output.append(replace(first, fantasy_team=selected.fantasy_team))
                continue
            occurrences = {(event.fantasy_league, event.fantasy_team,
                            self.owner_keys.get(str(event.fantasy_owner))) for event in copies}
            owners = {row[2] for row in occurrences if row[2]}
            if len(occurrences) == 1:
                label = first.fantasy_team
            elif len(owners) == 1 and next(iter(owners)) in self.users:
                label = self.users[next(iter(owners))].label
            else:
                label = None
            output.append(replace(first, fantasy_team=label))
        return output
