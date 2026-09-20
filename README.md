# Fantasy Football Live Scores on 64x32 LED Matrix

This Python program fetches live fantasy football scores from a Sleeper league and displays them on a 64x32 LED matrix connected to a Raspberry Pi.

## Local emulator

From the repository root:

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python main.py --emulator
```

The emulator opens in a browser at [http://localhost:8888](http://localhost:8888).
Press Control-C in the terminal to stop it.

By default, the app asks Sleeper for the current NFL week at startup and on each
data refresh. The week and other defaults can be overridden with command-line
options:

```bash
venv/bin/python main.py --emulator \
  --league-id YOUR_SLEEPER_LEAGUE_ID \
  --week 6 \
  --rotation-interval 10 \
  --data-refresh-interval 25
```

The same defaults can be set with `SLEEPER_LEAGUE_ID`, `DISPLAY_WEEK`,
`ROTATION_INTERVAL`, and `DATA_REFRESH_INTERVAL` environment variables.

## Multiple Sleeper and ESPN leagues

Copy `board_config.multileague.example.json` and pass it with `--config`:

```bash
cp board_config.multileague.example.json board_config.multileague.json
venv/bin/python main.py --emulator --config board_config.multileague.json
```

The `leagues` list controls display order. Each league may use `sleeper` or
`espn`, has a stable `league_id`, and may have a short `label`. The rotation is
league-name page, that league's matchups, then the next league. The global
`show_league_pages` default can be overridden on a league with
`"show_league_page": false`; `league_page_seconds` is global and defaults to
five seconds.

The top-level `users` registry maps readable keys to stable Sleeper user IDs
and/or ESPN member IDs. Matchup scope can be selected independently for every
league:

```json
{
  "key": "my-league",
  "platform": "sleeper",
  "league_id": "123456",
  "show_all_matchups": false,
  "display_users": ["christian"]
}
```

Set `show_all_matchups` to `true` to rotate through every matchup in that
league. Set it to `false` to show only matchups containing one of that league's
`display_users`. Multiple user keys may be listed. `default_display_users` is
used when a league omits `display_users`; a top-level `show_all_matchups` remains
available as a backward-compatible default when a league omits its own value.
This filter does not decide celebration ownership: all configured users remain
eligible for cross-league attribution.

Sleeper IDs can be copied from Sleeper's league users API. An ESPN member ID is
the `id` associated with the owner in the league API response (often enclosed
in braces), not the numeric fantasy team ID. ESPN public leagues require only
the league ID and season. For a private league, add a named credential profile:

```json
{
  "espn_credentials": {
    "primary": {"swid_env": "ESPN_SWID", "espn_s2_env": "ESPN_S2"}
  },
  "leagues": [{
    "key": "home-espn",
    "platform": "espn",
    "league_id": "12345678",
    "season": 2026,
    "credentials": "primary"
  }]
}
```

Export the two named environment variables before starting the process. Their
values come from the `SWID` and `espn_s2` cookies in a browser session signed in
to ESPN; keep them out of JSON and Git. For the Pi service, place them in a
root-readable systemd environment file and reference it with an
`EnvironmentFile=` drop-in.

Existing single-league CLI and `board_config.json` setups continue to work when
the config has no `leagues` list. Sleeper leagues retain calculated live
projections and median indicators. ESPN leagues use ESPN's live projected team
totals and team logos; median indicators are omitted because ESPN does not
provide the equivalent league-median result. Missing logos use the default.

### Win probability

Win probability is an optional local Monte Carlo estimate. Enable it in the
board config to alternate each matchup between projected score and win chance:

```json
"show_win_probability": true,
"win_probability_display": "alternate",
"win_probability_simulations": 5000
```

In `"alternate"` mode, each matchup shows projected points for the first half
of its rotation time and win probability for the second half, then advances to
the next matchup. Use `"probability"` instead to show win chance continuously.
The simulation uses the current score, projected final score, and the amount of
uncertainty remaining in active starters. It runs only when projections update,
uses a stable seed so unchanged inputs do not flicker, splits simulated ties
equally, and resolves completed matchups to their exact result. The CLI options
`--win-probability` / `--no-win-probability` and
`--win-probability-simulations N` override the config.

During the projected-score half, a green up chevron or red down chevron shows how
each team's projection changed at the latest projection refresh. The first
successful projection has no chevron, and unchanged projections show no chevron.
On median-enabled Sleeper leagues, the chevron is placed between the score and
the median medal.

Touchdown and big-play monitors run for every configured league. The same NFL
play is queued only once across leagues. One occurrence reveals its fantasy
team; multiple occurrences owned by the same configured user reveal that user
label; ownership by different users/teams reveals no attribution. ESPN starter
offensive events use ESPN roster and play-by-play data. ESPN D/ST attribution
uses the roster entry's NFL team mapping when ESPN provides it; missing provider
metadata cannot be inferred safely.

## Offline development replay

Stop the live emulator first (Control-C), then run:

```bash
venv/bin/python test_scoreboard.py
```

This runs the same rendering code as `main.py` using real **2025 Week 8** scores
from the previous SYPIP league (`1255668983974072320`). Five matchups rotate every
five seconds. No Sleeper or avatar requests are made; existing local logos or
`logos/default.jpg` are used. Production defaults remain unchanged.

Saved responses are in `fixtures/sleeper_2025_week8.json`, including lineups and
player points. Scores are final Week 8 results, not an in-game snapshot. Team
names and roster standings reflect the API at capture time, not necessarily
Week 8. NFL state is simulated as Week 8 / regular season.

Edit a copy of the fixture to try other scores, names, or edge cases:

```bash
venv/bin/python test_scoreboard.py --fixture fixtures/my_scenario.json --rotation-interval 3
venv/bin/python test_scoreboard.py --check
venv/bin/python -m unittest discover -s tests
```

Restart the launcher after editing the fixture. To test the empty preseason
screen, set `matchups` to `[]` and `season_type` to `"pre"` in your copy.

## Board layouts

The default `classic` layout has static, whole-character-truncated names below
the two logos. The alternative `diagonal` layout scrolls long names on separate
top and bottom rows; short names remain still.

```bash
venv/bin/python test_scoreboard.py --layout diagonal
venv/bin/python main.py --emulator --layout diagonal
venv/bin/python test_scoreboard.py --layout classic
```

To save your preference, set `"layout": "diagonal"` (or `"classic"`) in
`board_config.json`. Both launchers read this file automatically. Use
`--config path/to/board.json` for another JSON file; `--layout` overrides the
file's layout. This config is separate from `emulator_config.json`, which
controls emulator appearance and port settings.

On the 64×32 diagonal board:
- Team 1: 12×12 logo at top-left, scrolling name beside it, left-aligned score below.
- Team 2: 12×12 logo at bottom-right, scrolling name to its left, right-aligned score above.
- Two-pixel outer margins and two-pixel gaps between names and logos.
- Names are cropped to independent 46×6 windows, so they cannot overlap scores or logos.

Restart the running script after changing the layout or config. Both layouts
use complete-frame updates to avoid the previous partial-frame blinking.

## Touchdown celebrations

Both layouts interrupt the current matchup for **new starter touchdowns and 50+ yard big plays**.
Each celebration defaults to ten seconds. Touchdowns alternate yellow and orange
`TOUCHDOWN` text for the first half, then show the team-colored player name and
`XX YD TOUCHDOWN`. Big plays show the team-colored player name and
`XX YD RECEPTION` or `XX YD RUSH` for the full animation. The bottom 16 pixels play `assets/touchdown_runner.gif`, a
code-authored 8-bit football runner. Multiple events queue in detection order.
After the queue finishes, the same matchup resumes with its remaining rotation
time. Scores are polled on a background thread so requests cannot freeze the GIF.

Supported events:
- Starting skill players: rushing or receiving plays of 50 yards or more.
- A 50+ yard touchdown queues only the touchdown animation, never both.
- Individual starters: `RUSHING TD` and `RECEIVING TD` only (including QB rushing TDs).
- Starting D/ST: `INT TOUCHDOWN`, `FUM TOUCHDOWN`, or `RETURN TOUCHDOWN`.
- Return TDs include punt/kickoff and blocked-kick/field-goal returns.
- Passing TDs, bench players, individual return TDs, and two-point returns are excluded.

### Configure timing

`board_config.json` includes:

```json
{
  "layout": "classic",
  "touchdown_duration_seconds": 10,
  "touchdown_poll_interval_seconds": 30
}
```

The CLI overrides the selected config, in live and replay modes:

```bash
venv/bin/python main.py --emulator --layout diagonal --touchdown-duration 8
venv/bin/python test_scoreboard.py --layout diagonal --touchdown-demo --touchdown-duration 5
```

Stop any existing emulator on port 8888 first. The offline demo baselines at
startup, triggers its first two events after three seconds, and queues seven
celebrations in total. It covers rushing, receiving, interception, fumble, punt,
and kickoff-return events, plus silent negative cases and duplicate polls.
Restart the test script to replay the sequence. Normal replay without
`--touchdown-demo` remains static historical data and makes no live TD requests.

The additional fixture `fixtures/touchdown_demo.json` contains **synthetic**
time-indexed stat snapshots and ESPN-shaped scoring plays, not historical
play-by-play. Each snapshot documents its expected new events. Use
`--touchdown-scenario path/to/scenario.json` to load an edited scenario and
`--check` to validate it without launching the emulator.

### Data sources and limitations

- [Sleeper's API](https://docs.sleeper.com/#getting-matchups-in-a-league) supplies
  weekly starters and player identities. Its currently working, undocumented
  `/v1/stats/nfl/{season_type}/{season}/{week}` endpoint supplies rushing/receiving
  TD counters. Queries use the configured **league's season**, not today's year.
- Sleeper combines D/ST interceptions/fumbles in `def_td`; that field cannot
  reliably distinguish your requested labels. ESPN's public scoreboard and play-by-play endpoints supply per-play yardage,
  rush/reception participants, team colors, D/ST play type, and stable play IDs.
  For example, [this Week 8 summary](https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=401772869)
  identifies Tampa Bay's interception-return touchdown.
- Live detection is polled (default 30 seconds between completed polls), not
  push-based or instant. Provider updates/outages can add delay. Both stats and
  play-by-play endpoints are unofficial interfaces and may change.
- The first successful observation of each player/game/week establishes a
  baseline without replaying old TDs. Newly added starters also baseline.
  An unavailable feed preserves its previous baseline; after an initial outage,
  its first successful response is still treated as startup, not new events.
- Offensive counters retain a high-water mark to suppress correction/restoration
  duplicates. A later TD that merely restores a permanently corrected count
  cannot be distinguished from restoration and may be skipped. D/ST uses play
  IDs and does not have this counter ambiguity.
- Only events detected while this process is running are queued. Startup/restart
  intentionally discards previous events. No fake labels or points-based guesses
  are used if a source is unavailable.

Regenerate the original pixel-art GIF with `venv/bin/python touchdown_animation.py`.
Run all offline checks with `venv/bin/python -m unittest discover -s tests -v`.

## Live projected scores

Matchup screens show estimated final scores whenever projection data is available,
falling back to actual scores while projections load or if no projection has ever
succeeded. The estimate combines Sleeper's weekly starter projections and current
fantasy points with ESPN's game state:

- not started: the full pregame projection;
- in progress: actual points plus the pregame expectation for the fraction of
  regulation time remaining;
- final or overtime: actual points;
- unavailable game state: the greater of actual and pregame projected points.

The calculation selects Sleeper's standard, half-PPR, or PPR projection based on
the league's reception scoring. Other custom bonuses are not currently modeled.
Projection failures retain the last successful totals and never interrupt live
score or celebration rendering. Live projection inputs poll on the same default
25-second interval as matchup scores; weekly pregame projections and the player
catalogue are cached for the process.

When Sleeper's **Extra Game Each Week Against League Median** setting is enabled,
the diagonal layout places a small gold circle two visible pixels from each score for
teams projected strictly above the league median. The live median is calculated
from all projected team totals and updates with the same 25-second projection
refresh. A team exactly at the median does not receive a medal.

Team logos prefer a custom URL in Sleeper league metadata and fall back to the
user's standard Sleeper avatar. Logos download once at process startup, are
checked for a changed source URL every 25-second matchup refresh, and download
again only after an avatar change. Updated files invalidate the in-memory image
cache immediately.

## Physical LED board

Physical-board mode requires a Raspberry Pi configured with a 64x32 RGB LED
matrix, plus the `rpi-rgb-led-matrix` Python bindings. Run without `--emulator`:

```bash
venv/bin/python main.py
```

To build the bindings on the Raspberry Pi:

```bash
sudo apt-get update
sudo apt-get install -y make python3-dev cython3
cd rpi-rgb-led-matrix
make build-python
sudo make install-python
```

### Manual service alongside Spotify Board

The Pi deployment includes a manual-only `fantasy-scoreboard.service`. It is
disabled at boot and has no restart policy. The Spotify Board manager is the sole
owner of display switching: its `fantasy` mode stops Spotify and Sportsmatrix
before starting this service, while its other modes stop this service before
starting another display.

Clone the project and install the service once:

```bash
cd /home/christiangeer
git clone https://github.com/geerc/fantasy-scoreboard.git
cd /home/christiangeer/fantasy-scoreboard
./scripts/install_pi_service.sh
```

Pull future versions while the service is stopped, then select Fantasy mode:

```bash
sudo systemctl stop fantasy-scoreboard.service
cd /home/christiangeer/fantasy-scoreboard
git pull --ff-only
/home/christiangeer/spotify_board/.venv/bin/spotify-board-control fantasy
```

Manual controls (also suitable for iOS **Run Script over SSH** actions):

```bash
/home/christiangeer/spotify_board/.venv/bin/spotify-board-control fantasy
/home/christiangeer/spotify_board/.venv/bin/spotify-board-control off
systemctl is-active fantasy-scoreboard.service
journalctl -u fantasy-scoreboard.service -f
```
