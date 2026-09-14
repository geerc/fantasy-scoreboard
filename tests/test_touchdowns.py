import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageChops

from layout_config import resolve_touchdown_settings
from name_scroll import NameRenderer
from touchdown_animation import ASSET, CelebrationRenderer
from touchdown_source import SleeperTouchdownSource
from touchdowns import Touchdown, TouchdownDetector, CelebrationQueue, ReplayTouchdownMonitor, dst_kind, play_actor
import test_scoreboard as replay


def scenario():
    with (replay.PROJECT_DIR / "fixtures/touchdown_demo.json").open() as stream:
        return json.load(stream)


class DetectorTests(unittest.TestCase):
    def test_complete_scenario_and_duplicate_polls(self):
        detector = TouchdownDetector()
        count = 0
        for entry in scenario()["snapshots"]:
            events = detector.observe(entry["snapshot"])
            self.assertEqual([e.kind for e in events], entry["expected_new_events"], entry["note"])
            count += len(events)
            self.assertEqual(detector.observe(entry["snapshot"]), [])
        self.assertEqual(count, 7)

    def test_new_starter_is_baselined_not_replayed(self):
        detector = TouchdownDetector()
        snapshot = deepcopy(scenario()["snapshots"][0]["snapshot"])
        detector.observe(snapshot)
        snapshot["starters"].append("bench-wr")
        snapshot["stats"]["bench-wr"]["rec_td"] = 2
        self.assertEqual(detector.observe(snapshot), [])
        snapshot["stats"]["bench-wr"]["rec_td"] = 3
        self.assertEqual([e.name for e in detector.observe(snapshot)], ["Bench Receiver"])

    def test_multiple_td_increase_and_week_rollover(self):
        detector = TouchdownDetector()
        snapshot = deepcopy(scenario()["snapshots"][0]["snapshot"])
        detector.observe(snapshot)
        snapshot["stats"]["8138"]["rush_td"] = 2
        events = detector.observe(snapshot)
        self.assertEqual(len(events), 2)
        self.assertNotEqual(events[0].event_id, events[1].event_id)
        snapshot["context"][-1] += 1
        self.assertEqual(detector.observe(snapshot), [])

    def test_failed_stats_poll_preserves_baseline(self):
        detector = TouchdownDetector()
        snapshot = deepcopy(scenario()["snapshots"][0]["snapshot"])
        detector.observe(snapshot)
        failed = deepcopy(snapshot)
        failed["stats"] = None
        self.assertEqual(detector.observe(failed), [])
        snapshot["stats"]["8138"]["rush_td"] = 1
        self.assertEqual(len(detector.observe(snapshot)), 1)

    def test_first_success_after_failure_is_baseline(self):
        detector = TouchdownDetector()
        snapshot = deepcopy(scenario()["snapshots"][0]["snapshot"])
        failed = deepcopy(snapshot)
        failed["stats"] = None
        detector.observe(failed)
        snapshot["stats"]["8138"]["rush_td"] = 3
        self.assertEqual(detector.observe(snapshot), [])

    def test_missing_rows_and_invalid_counts_do_not_reset_or_crash(self):
        detector = TouchdownDetector()
        snapshot = deepcopy(scenario()["snapshots"][0]["snapshot"])
        detector.observe(snapshot)
        del snapshot["stats"]["11647"]
        self.assertEqual(detector.observe(snapshot), [])
        for bad in (None, -1, 1.5, float("nan"), float("inf"), "2"):
            snapshot["stats"]["11647"] = {"rush_td": bad}
            self.assertEqual(detector.observe(snapshot), [])
        snapshot["stats"]["11647"] = {"rush_td": 2}
        self.assertEqual(len(detector.observe(snapshot)), 1)

    def test_big_play_touchdown_priority_and_delayed_participants(self):
        detector = TouchdownDetector()
        player = {"full_name": "Justin Jefferson", "team": "MIN", "position": "WR"}
        base = {"context": ["league", "2026", "regular", 1], "starters": ["jj"],
                "players": {"jj": player}, "stats": {"jj": {"rec_td": 0}},
                "games": [{"id": "game", "plays": []}], "play_by_play_ready": True,
                "team_colors": {"MIN": "#4f2683"}}
        detector.observe(base)
        def play(pid, yards, scoring=False, participants=True):
            return {"id": pid, "type": {"text": "Pass Reception"},
                    "text": ("S.Darnold pass to J.Jefferson for yards" if participants else "Player data pending"),
                    "statYardage": yards, "scoringPlay": scoring, "offenseTeam": "MIN",
                    "participants": ([{"type": "receiver",
                        "athlete": {"fullName": "Justin Jefferson"}}] if participants else [])}
        current = deepcopy(base)
        current["stats"]["jj"]["rec_td"] = 1
        current["games"][0]["plays"] = [play("big", 50), play("td", 65, True)]
        events = detector.observe(current)
        self.assertEqual([event.kind for event in events], ["BIG PLAY", "TOUCHDOWN"])
        self.assertEqual([(event.yards, event.play_type, event.team_color) for event in events],
                         [(50, "RECEPTION", "#4f2683"), (65, "RECEPTION", "#4f2683")])
        self.assertEqual(detector.observe(current), [])

        delayed = deepcopy(current)
        delayed["games"][0]["plays"].append(play("late", 55, participants=False))
        self.assertEqual(detector.observe(delayed), [])
        delayed["games"][0]["plays"][-1] = play("late", 55, participants=True)
        self.assertEqual([event.kind for event in detector.observe(delayed)], ["BIG PLAY"])

    def test_completed_espn_touchdown_types_are_recognized(self):
        players = {"wr": {"full_name": "Jaxon Smith-Njigba", "team": "SEA", "position": "WR"},
                   "qb": {"full_name": "Drew Lock", "team": "SEA", "position": "QB"}}
        play = {"type": {"text": "Passing Touchdown"}, "offenseTeam": "SEA",
                "text": "D.Lock pass to J.Smith-Njigba for 45 yards, TOUCHDOWN."}
        self.assertEqual(play_actor(play, {"wr", "qb"}, players), ("wr", "receiver"))
        self.assertEqual(play_actor(play, {"qb"}, players, "passer"), ("qb", "passer"))
        rush = {"type": {"text": "Rushing Touchdown"}, "offenseTeam": "SEA",
                "text": "D.Lock up the middle for 2 yards, TOUCHDOWN."}
        self.assertEqual(play_actor(rush, {"qb"}, players), ("qb", "rusher"))

    def test_nonstarting_receiver_credits_started_qb(self):
        qb = {"full_name": "Joe Burrow", "team": "CIN", "position": "QB"}
        receiver = {"full_name": "Ja Marr Chase", "team": "CIN", "position": "WR"}
        play = {"id": "pass-td", "type": {"text": "Pass Reception"},
                "text": "J.Burrow pass to J.Chase for 67 yards", "statYardage": 67,
                "scoringPlay": True, "offenseTeam": "CIN", "participants": [
                    {"type": "passer", "athlete": {"fullName": "Joe Burrow"}},
                    {"type": "receiver", "athlete": {"fullName": "Ja Marr Chase"}}]}
        base = {"context": ["league", "2026", "regular", 1], "starters": ["qb"],
                "owned_players": ["qb"], "players": {"qb": qb}, "stats": {},
                "games": [{"id": "game", "plays": []}], "play_by_play_ready": True,
                "team_colors": {"CIN": "#fb4f14"}, "fantasy_teams": {"qb": "Burrow My Heart"}}
        detector = TouchdownDetector()
        detector.observe(base)
        current = deepcopy(base)
        current["games"][0]["plays"] = [play]
        events = detector.observe(current)
        self.assertEqual([(e.name, e.yards, e.play_type, e.fantasy_team) for e in events],
                         [("Joe Burrow", 67, "PASS", "Burrow My Heart")])

        owned = deepcopy(base)
        owned["owned_players"].append("wr")
        owned["players"]["wr"] = receiver
        detector = TouchdownDetector()
        detector.observe(owned)
        owned["games"][0]["plays"] = [play]
        owned_events = detector.observe(owned)
        self.assertEqual([(e.name, e.play_type) for e in owned_events],
                         [("Joe Burrow", "PASS")])

        benched_qb = deepcopy(owned)
        benched_qb["starters"] = []
        detector = TouchdownDetector()
        detector.observe(benched_qb)
        benched_qb["games"][0]["plays"] = [play]
        self.assertEqual(detector.observe(benched_qb), [])

    def test_return_types_and_offensive_exclusions(self):
        for text in ("Punt Return Touchdown", "Kickoff Return Touchdown", "Blocked Punt Touchdown",
                     "Blocked Field Goal Touchdown", "Missed Field Goal Return Touchdown"):
            play = {"scoringType": {"name": "touchdown"}, "type": {"text": text}}
            self.assertEqual(dst_kind(play), "RETURN TOUCHDOWN")
        for text in ("Passing Touchdown", "Rushing Touchdown", "Fumble Recovery (Own) Touchdown"):
            play = {"scoringType": {"name": "touchdown"}, "type": {"text": text}}
            self.assertIsNone(dst_kind(play))
        self.assertIsNone(dst_kind({"scoringType": {"name": "two-point-conversion"},
                                   "type": {"text": "Interception Return"}}))

    def test_dst_failure_then_recovery_and_new_defense(self):
        data = scenario()
        initial = deepcopy(data["snapshots"][0]["snapshot"])
        detector = TouchdownDetector()
        detector.observe(initial)
        missing = deepcopy(initial)
        missing["games"] = []
        detector.observe(missing)
        later = deepcopy(data["snapshots"][3]["snapshot"])
        later["stats"] = initial["stats"]
        self.assertEqual(len(detector.observe(later)), 4)
        initial["starters"].remove("IND")
        detector = TouchdownDetector()
        detector.observe(initial)
        later["stats"] = initial["stats"]
        self.assertEqual([e.player_id for e in detector.observe(later)], ["HOU", "PIT"])


class PlaybackTests(unittest.TestCase):
    def test_duration_queue_boundaries(self):
        first = Touchdown("1", "a", "Player A", "RUSHING TD")
        second = Touchdown("2", "b", "Player B", "RECEIVING TD")
        queue = CelebrationQueue(5)
        self.assertEqual(queue.step(0, [first, second]), (first, 0))
        self.assertEqual(queue.step(4.99)[0], first)
        self.assertEqual(queue.step(5), (second, 0))
        self.assertIsNone(queue.step(10))

    def test_config_override_and_invalid_durations(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "board.json"
            path.write_text('{"touchdown_duration_seconds": 8, "touchdown_poll_interval_seconds": 15}')
            self.assertEqual(resolve_touchdown_settings(config=path), (8, 15))
            self.assertEqual(resolve_touchdown_settings(duration=5, config=path), (5, 15))
            for bad in (0, -1, float("nan"), float("inf"), True, "5"):
                with self.assertRaises(ValueError):
                    resolve_touchdown_settings(duration=bad, config=path)

    def test_real_gif_and_two_display_phases(self):
        with Image.open(ASSET) as gif:
            self.assertEqual(gif.size, (64, 16))
            self.assertGreater(gif.n_frames, 20)
        names = NameRenderer(replay.PROJECT_DIR / "rpi-rgb-led-matrix/fonts/4x6.bdf")
        renderer = CelebrationRenderer(names)
        event = Touchdown("1", "11647", "Bucky Irving", "TOUCHDOWN", 54, "RUSH", "#4f2683")
        first = renderer.render(event, 0, 5)
        orange = renderer.render(event, .3, 5)
        second = renderer.render(event, 2.5, 5)
        self.assertIsNotNone(first.crop((0, 0, 64, 16)).getbbox())
        yellow_pixels = set(first.crop((0, 0, 64, 16)).getdata())
        orange_pixels = set(orange.crop((0, 0, 64, 16)).getdata())
        self.assertEqual(yellow_pixels, {(0, 0, 0), (255, 220, 0)})
        self.assertEqual(orange_pixels, {(0, 0, 0), (255, 128, 0)})
        self.assertEqual(first.crop((0, 0, 64, 16)).getchannel("R").tobytes(),
                         orange.crop((0, 0, 64, 16)).getchannel("R").tobytes())
        expected = Image.new("RGB", (64, 16))
        player_name = names.bitmap(event.name)
        player_mask = player_name.convert("L")
        colored_name = Image.new("RGB", player_name.size, "#4f2683")
        expected.paste(colored_name, ((64 - player_name.width) // 2, 1), player_mask)
        label = names.bitmap("54 YD RUSH")
        expected.paste(label, ((64 - label.width) // 2, 9))
        self.assertIsNone(ImageChops.difference(expected, second.crop((0, 0, 64, 16))).getbbox())
        self.assertIsNotNone(ImageChops.difference(first.crop((0, 16, 64, 32)),
                                                   second.crop((0, 16, 64, 32))).getbbox())

    def test_big_play_text_and_team_color(self):
        names = NameRenderer(replay.PROJECT_DIR / "rpi-rgb-led-matrix/fonts/4x6.bdf")
        renderer = CelebrationRenderer(names)
        event = Touchdown("big", "jj", "J JEFFERSON", "BIG PLAY", 54, "RECEPTION", "#4f2683",
                          "THE GRIDIRON KINGS FOREVER")
        frame = renderer.render(event, 1, 5)
        name_mask = names.bitmap(event.name).convert("L")
        name_x = (64 - name_mask.width) // 2
        colors = {frame.getpixel((name_x + x, 1 + y)) for y in range(name_mask.height)
                  for x in range(name_mask.width) if name_mask.getpixel((x, y))}
        self.assertEqual(colors, {(79, 38, 131)})
        label = names.bitmap("54 YD RECEPTION")
        label_x = (64 - label.width) // 2
        self.assertIsNone(ImageChops.difference(
            label, frame.crop((label_x, 9, label_x + label.width, 15))).getbbox())

    def test_fantasy_team_reveals_and_clips_without_ellipsis(self):
        names = NameRenderer(replay.PROJECT_DIR / "rpi-rgb-led-matrix/fonts/4x6.bdf")
        renderer = CelebrationRenderer(names)
        team = "THE GRIDIRON KINGS FOREVER"
        event = Touchdown("big", "jj", "J JEFFERSON", "BIG PLAY", 54,
                          "RECEPTION", "#4f2683", team)
        frame = renderer.render(event, 4.999, 5).crop((0, 16, 64, 32))
        expected = renderer.frames[-1].copy()
        clipped = names.bitmap(team).crop((0, 0, 62, names.HEIGHT))
        expected.paste(clipped, (2, 5), clipped.convert("L"))
        self.assertIsNone(ImageChops.difference(expected, frame).getbbox())
        self.assertNotIn(names.bitmap("...").tobytes(), frame.tobytes())

    def test_interrupt_and_resume_same_matchup(self):
        # Simulate time through main.py, without threads, network, or a browser.
        clock = [0.0]
        frames = []
        canvas = Mock()
        matrix = Mock(width=64)
        matrix.CreateFrameCanvas.return_value = canvas
        graphics = Mock()
        graphics.Font.return_value.CharacterWidth.return_value = 5
        marker = [None]
        canvas.Clear.side_effect = lambda: marker.__setitem__(0, "matchup")
        def image(img, *position):
            if img.size == (64, 32):
                marker[0] = "celebration"
        canvas.SetImage.side_effect = image
        def swap(frame):
            texts = [call.args[5] for call in graphics.DrawText.call_args_list[-2:]]
            frames.append((clock[0], marker[0], texts))
            return canvas
        matrix.SwapOnVSync.side_effect = swap
        def sleep(_):
            clock[0] += .05
            if clock[0] > 8:
                raise KeyboardInterrupt
        demo = deepcopy(scenario())
        demo["snapshots"] = demo["snapshots"][:3]  # baseline, two TDs, repeat
        emulator = SimpleNamespace(RGBMatrix=Mock(return_value=matrix),
                                   RGBMatrixOptions=SimpleNamespace, graphics=graphics)
        with patch.dict("sys.modules", {"RGBMatrixEmulator": emulator}), \
                patch.object(replay.scoreboard.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(replay.scoreboard.time, "sleep", side_effect=sleep), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                replay.run_replay(replay.load_fixture(replay.DEFAULT_FIXTURE),
                                  rotation_interval=4, data_refresh_interval=1000,
                                  touchdown_duration=1, touchdown_scenario=demo)
        before = next(f for f in reversed(frames) if f[0] < 3 and f[1] == "matchup")
        after = next(f for f in frames if f[0] > 5 and f[1] == "matchup")
        # Projection alternation may change the numeric text during an interrupt,
        # but both frames must still represent the same third fixture matchup.
        expected_team2 = {"121.6"}
        self.assertIn(before[2][0], expected_team2)
        self.assertIn(after[2][0], expected_team2)
        self.assertTrue(any(f[1] == "celebration" for f in frames))
        self.assertTrue(all(f[1] == "celebration" for f in frames if 3.1 < f[0] < 5))
        self.assertTrue(any(f[2] != before[2] for f in frames if f[1] == "matchup" and f[0] > 6.3))


class SourceTests(unittest.TestCase):
    def test_live_adapter_uses_league_season_and_weekly_starters(self):
        schedule = {"events": [{"id": "g", "competitions": [{"competitors": [
            {"team": {"id": "11", "abbreviation": "IND", "color": "002c5f"}}, {"team": {"id": "34", "abbreviation": "HOU", "color": "03202f"}}]}],
            "status": {"type": {"state": "in"}}}]}
        calls = []
        def get(url, **params):
            calls.append((url, params))
            if url.endswith('/league/league'): return {"season": "2025", "season_type": "regular"}
            if '/matchups/' in url: return [{"roster_id": 1, "starters": ["11647", "IND"], "players": ["11647", "bench"]}]
            if url.endswith('/league/league/users'): return [{"user_id": "owner", "display_name": "Gridiron Kings", "metadata": {}}]
            if url.endswith('/league/league/rosters'): return [{"roster_id": 1, "owner_id": "owner"}]
            if url.endswith('/players/nfl'): return {"11647": {"full_name": "Bucky Irving"}, "IND": {"position": "DEF"}}
            if '/stats/' in url: return {"11647": {"rush_td": 1}}
            if url.endswith('/scoreboard'): return schedule
            if url.endswith('/summary'): return {"scoringPlays": [], "drives": {"previous": [{"plays": [
                {"id": "p", "type": {"text": "Rush"}, "text": "B.Irving for 52 yards",
                 "statYardage": 52, "scoringPlay": False, "start": {"team": {"id": "11"}}}
            ]}]}}
            raise AssertionError(url)
        with patch("touchdown_source.get_json", side_effect=get):
            source = SleeperTouchdownSource("league")
            result = source.poll(8)
            source.poll(8)
        self.assertEqual(result["context"], ["league", "2025", "regular", 8])
        self.assertEqual(result["starters"], ["11647", "IND"])
        self.assertEqual(result["fantasy_teams"]["11647"], "Gridiron Kings")
        self.assertTrue(any('/stats/nfl/regular/2025/8' in url for url, _ in calls))
        self.assertEqual(sum(url.endswith('/players/nfl') for url, _ in calls), 1)
        self.assertTrue(result["play_by_play_ready"])
        self.assertEqual(result["team_colors"]["IND"], "#002c5f")
        self.assertEqual(result["games"][0]["plays"][0]["offenseTeam"], "IND")


if __name__ == "__main__":
    unittest.main()
