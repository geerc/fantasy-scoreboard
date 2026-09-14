import time
import requests
import argparse
import os
import sys
import logging
from PIL import Image
from sleeper_wrapper import League
from name_scroll import NameRenderer
from layout_config import (add_layout_arguments, resolve_layout,
                           add_touchdown_arguments, resolve_touchdown_settings)
from touchdowns import CelebrationQueue
from touchdown_source import create_touchdown_monitor
from touchdown_animation import CelebrationRenderer
from live_projections import LiveProjectionMonitor

# --- Configuration: can be set via CLI args or environment variables ---
DEFAULT_LEAGUE_ID = os.getenv("SLEEPER_LEAGUE_ID", "1389341850288009216")
DISPLAY_WEEK_OVERRIDE = os.getenv("DISPLAY_WEEK")
DEFAULT_WEEK = int(DISPLAY_WEEK_OVERRIDE) if DISPLAY_WEEK_OVERRIDE else None
DEFAULT_ROTATION_INTERVAL = int(os.getenv("ROTATION_INTERVAL", "10"))
DEFAULT_DATA_REFRESH_INTERVAL = int(os.getenv("DATA_REFRESH_INTERVAL", "25"))
PROJECTION_DISPLAY_INTERVAL = 3
SLEEPER_NFL_STATE_URL = "https://api.sleeper.app/v1/state/nfl"

# scrolling state: {matchup_index: offset_px}
scroll_offsets = {}

# per-key measured text widths (px) for wrapping
scroll_widths = {}

# milliseconds between scroll steps
SCROLL_STEP_MS = 200
last_scroll_time = time.time()


# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fantasy_led")


def get_current_nfl_state():
    """Return Sleeper's current NFL week and season type."""
    response = requests.get(SLEEPER_NFL_STATE_URL, timeout=10)
    response.raise_for_status()
    state = response.json()
    week = state.get("week")
    if not isinstance(week, int) or week < 1:
        raise ValueError(f"Sleeper returned an invalid NFL week: {week!r}")
    return week, state.get("season_type")


def main():
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(description="Run LED board with options.")
    parser.add_argument(
        "--emulator",
        action="store_true",
        help="Use the browser-based RGBMatrixEmulator instead of the physical LED board.",
    )
    parser.add_argument("--league-id", default=DEFAULT_LEAGUE_ID, help="Sleeper league ID (env SLEEPER_LEAGUE_ID)")
    parser.add_argument(
        "--week",
        type=int,
        default=DEFAULT_WEEK,
        help="Week to display; defaults to Sleeper's current NFL week (env DISPLAY_WEEK)",
    )
    parser.add_argument("--rotation-interval", type=int, default=DEFAULT_ROTATION_INTERVAL,
                        help="Seconds between screens (env ROTATION_INTERVAL)")
    parser.add_argument("--data-refresh-interval", type=int, default=DEFAULT_DATA_REFRESH_INTERVAL,
                        help="Seconds between data refreshes (env DATA_REFRESH_INTERVAL)")

    add_layout_arguments(parser)
    add_touchdown_arguments(parser)
    args = parser.parse_args()
    try:
        layout = resolve_layout(args.layout, args.config)
        touchdown_duration, touchdown_poll_interval = resolve_touchdown_settings(
            args.touchdown_duration, args.touchdown_poll_interval, args.config)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    logger.info("Using %s board layout", layout)

    league_id = args.league_id
    week_is_dynamic = args.week is None
    try:
        current_week, season_type = get_current_nfl_state()
    except (requests.RequestException, ValueError) as error:
        current_week = None
        season_type = None
        logger.warning("Could not determine the current NFL state: %s", error)

    if args.week is not None:
        display_week = args.week
        logger.info("Displaying configured NFL week %s", display_week)
    elif current_week is not None:
        display_week = current_week
        logger.info("Sleeper reports the current NFL week as %s", display_week)
    else:
        display_week = 1
        logger.warning("Falling back to NFL week %s", display_week)
    rotation_interval = args.rotation_interval
    data_refresh_interval = args.data_refresh_interval

    # Import the appropriate RGBMatrix package
    if args.emulator:
        from RGBMatrixEmulator import RGBMatrix, RGBMatrixOptions, graphics
        print("Running in emulator mode.")

        # Set up the LED matrix options
        options = RGBMatrixOptions()
        options.rows = 32
        options.cols = 64
        options.brightness = 100
        #    options.disable_hardware_pulsing = False  # Disable hardware pulsing to avoid needing root permissions
        #options.pwm_lsb_nanoseconds = 300  # Improve LED refresh quality
        matrix = RGBMatrix(options=options)

        # Create the graphics canvas
        canvas = matrix.CreateFrameCanvas()


    else:
        from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics
        print("Running on physical LED board.")

        # Set up the LED matrix options
        options = RGBMatrixOptions()
        options.rows = 32
        options.cols = 64
        options.brightness = 40
        options.hardware_mapping = 'adafruit-hat'  # 'regular' for most, but it could be different
        options.gpio_slowdown = 4  # Try values like 1, 2, or 3 for slowdown
        # This root-owned service needs to refresh cached logos after GPIO setup.
        options.drop_privileges = False
        #options.pwm_lsb_nanoseconds = 150  # Improve LED refresh quality

        matrix = RGBMatrix(options=options)

        # Create the graphics canvas
        canvas = matrix.CreateFrameCanvas()

    # Set up Sleeper League
    my_league = League(league_id)

    # Load a font
    try:
        # Load a font
        text_font = graphics.Font()
        text_font.LoadFont("rpi-rgb-led-matrix/fonts/4x6.bdf")  # Adjust font path if needed
        name_renderer = NameRenderer("rpi-rgb-led-matrix/fonts/4x6.bdf")

        score_font = graphics.Font()
        score_font.LoadFont("rpi-rgb-led-matrix/fonts/5x7.bdf")
    except Exception as e:
        logger.exception("Failed to load fonts. Check font path and that rpi-rgb-led-matrix is installed.")
        raise

    # Set colors
    white = graphics.Color(255, 255, 255)
    red = graphics.Color(255, 0, 0)
    green = graphics.Color(0, 255, 0)
    black = graphics.Color(0, 0, 0)

    # Create the 'logos' directory in the current working directory
    logos_dir = os.path.join(os.getcwd(), "logos")  # Constructs the path for 'logos' in the current directory
    os.makedirs(logos_dir, exist_ok=True)  # Creates the directory if it doesn't already exist

    # Logo cache (PIL Image objects)
    logo_cache = {}

    def preload_logo(path: str):
        if path in logo_cache:
            return logo_cache[path]
        try:
            img = Image.open(path).convert("RGB")
            img = img.resize((20, 20))
            logo_cache[path] = img
            logger.debug(f"Preloaded logo: {path}")
            return img
        except Exception:
            logger.exception(f"Failed to preload logo {path}. Using default.")
            # ensure default is cached
            if default_logo_path not in logo_cache:
                preload_logo(default_logo_path)
            return logo_cache.get(default_logo_path)

    def get_team_data(data_league, week):
        """Retrieve detailed team data for each matchup."""

        # pull weekly matchups
        matchups = data_league.get_matchups(week)

        users = data_league.get_users()  # List of users with 'user_id' and 'display_name'
        rosters = data_league.get_rosters()  # List of rosters with 'owner_id', 'roster_id', 'wins', 'losses', 'ties'

        # download user avatars
        for user in users:
            logo_url = user['metadata'].get("avatar")
            if logo_url:
                try:
                    # Fetch the image data
                    response = requests.get(logo_url)
                    response.raise_for_status()  # Raise exception for HTTP errors

                    # Save the image to the 'logos' directory
                    file_path = os.path.join(logos_dir, f"{user['user_id']}.png")
                    with open(file_path, "wb") as logo_file:
                        logo_file.write(response.content)
                    print(f"Downloaded logo for user {user['user_id']} to {file_path}")
                except Exception as e:
                    print(f"Failed to download logo for user {user['user_id']}: {e}")
            else:
                print(f"No avatar URL found for user {user['user_id']}")

        # Create a map for user_id to team_name (fallback to 'display_name' if team_name is not set)
        user_map = {
            user["user_id"]: {
                'team_name': user['metadata'].get('team_name', user['display_name']),
                'display_name': user['display_name'],
            }
            for user in users
        }

        # Create a mapping of roster_id to team stats
        roster_map = {
            roster['roster_id']: {
                'team_name': user_map.get(roster['owner_id'], {}).get('team_name', "Unknown Team"),
                'display_name': user_map.get(roster['owner_id'], {}).get('display_name', "Unknown Owner"),
                'wins': roster['settings']['wins'],
                'losses': roster['settings']['losses'],
                'ties': roster['settings']['ties'],
                'owner_id': roster['owner_id'],
            }
            for roster in rosters
        }

        # Group matchups by matchup_id
        matchup_groups = {}
        for team in matchups:
            matchup_id = team["matchup_id"]
            if matchup_id not in matchup_groups:
                matchup_groups[matchup_id] = []
            matchup_groups[matchup_id].append(team)

        # Create a detailed list of matchups
        detailed_matchups = []
        for matchup_id, teams in matchup_groups.items():
            if len(teams) != 2:
                print(f"Invalid matchup pair in matchup_id {matchup_id}: {teams}")
                continue

            team1, team2 = teams

            # Retrieve details for each team
            team1_details = roster_map[team1["roster_id"]]
            team2_details = roster_map[team2["roster_id"]]

            # Determine logo file names using owner_id
            team1_logo = f"{team1_details['owner_id']}.png"
            team2_logo = f"{team2_details['owner_id']}.png"

            # Check if the logo files exist
            team1_logo_path = os.path.join(logos_dir, team1_logo)
            team2_logo_path = os.path.join(logos_dir, team2_logo)

            team1_logo_file = team1_logo_path if os.path.exists(team1_logo_path) else os.path.join(logos_dir, 'default.jpg')
            team2_logo_file = team2_logo_path if os.path.exists(team2_logo_path) else os.path.join(logos_dir, 'default.jpg')

            print('team1_details:\n', team1_details)

            detailed_matchups.append({
                "team1": {
                    "roster_id": str(team1["roster_id"]),
                    "name": team1_details["team_name"],
                    "wins": team1_details["wins"],
                    "losses": team1_details["losses"],
                    "ties": team1_details["ties"],
                    "points": team1["points"],
                    "logo": team1_logo_file
                },
                "team2": {
                    "roster_id": str(team2["roster_id"]),
                    "name": team2_details["team_name"],
                    "wins": team2_details["wins"],
                    "losses": team2_details["losses"],
                    "ties": team2_details["ties"],
                    "points": team2["points"],
                    "logo": team2_logo_file
                }
            })

        return detailed_matchups

    def draw_matchup(canvas, team1_data, team2_data, bg_color, show_projection=False):
        # Compose the entire frame offscreen; only SwapOnVSync publishes it.
        if layout == "diagonal":
            draw_diagonal(canvas, team1_data, team2_data, show_projection)
        else:
            draw_logos(canvas, team1_data['logo'], team2_data['logo'])
            canvas.SetImage(name_renderer.team_window(team1_data.get('name'), 30), 1, 17, False)
            canvas.SetImage(name_renderer.team_window(
                team2_data.get('name'), 30, right_align=True), 33, 17, False)
            draw_scores(canvas, team1_data, team2_data, show_projection)
        return canvas

    def draw_empty_screen(canvas):
        """Show a useful placeholder while the league has no scheduled matchups."""
        canvas.Clear()
        graphics.DrawText(canvas, text_font, 2, 12, white, "NO MATCHUPS")
        period_label = "PRESEASON" if season_type == "pre" else f"WEEK {display_week}"
        graphics.DrawText(canvas, text_font, 2, 23, white, period_label)
        return matrix.SwapOnVSync(canvas)

    def draw_score_text(canvas, x, baseline_y, color, value):
        """Draw the 5x7 score face with a one-pixel bold overdraw."""
        graphics.DrawText(canvas, score_font, x, baseline_y, color, value)
        graphics.DrawText(canvas, score_font, x + 1, baseline_y, color, value)

    def display_points(team, show_projection):
        value = team.get("projection") if show_projection else team.get("points")
        if value is None:
            value = team.get("points", 0)
        if show_projection and team.get("projection") is not None:
            text = f"{float(value):.1f}".rstrip("0").rstrip(".")
            return f"P{text}"
        return str(value)

    def draw_scores(canvas, team1, team2, show_projection=False):
        left_x = 1
        baseline_y = 31
        team1_score = team1.get("projection") if show_projection else team1["points"]
        team2_score = team2.get("projection") if show_projection else team2["points"]
        team1_score = team1["points"] if team1_score is None else team1_score
        team2_score = team2["points"] if team2_score is None else team2_score

        # Panel width detection fallback
        panel_width = getattr(matrix, 'width', None) or getattr(matrix, 'Width', None) or 64

        # distance from right edge to the right-most pixel of the score text
        # (make this negative to push further right as needed)
        right_margin = 1

        # Per-character pixel widths for the small bitmap font.
        # Adjust these if your font metrics differ (e.g. 5 or 7 px digits).
        CHAR_WIDTHS = {
            '0': 6, '1': 4, '2': 6, '3': 6, '4': 6,
            '5': 6, '6': 6, '7': 6, '8': 6, '9': 6,
            '.': 2,  # decimal point is typically narrower
            '-': 4,  # negative sign, if applicable
        }

        def text_pixel_width(s: str) -> int:
            # Sum per-character widths; unknown chars fallback to 6px
            return sum(CHAR_WIDTHS.get(ch, 6) for ch in s)

        s1 = display_points(team1, show_projection)
        s2 = display_points(team2, show_projection)

        s1_w = text_pixel_width(s1)
        s2_w = text_pixel_width(s2)

        # right-aligned x for team2 (so right-most pixel sits at panel_width - right_margin)
        team2_x = panel_width - right_margin - s2_w - 1

        # Guard against overlap with left team; ensure minimum separation
        min_sep = 14  # minimum pixels between left score x and right score x
        if team2_x <= left_x + min_sep:
            team2_x = left_x + min_sep

        # draw using color rules
        if team1_score > team2_score:
            draw_score_text(canvas, left_x, baseline_y, green, s1)
            draw_score_text(canvas, team2_x, baseline_y, red, s2)
        elif team2_score > team1_score:
            draw_score_text(canvas, left_x, baseline_y, red, s1)
            draw_score_text(canvas, team2_x, baseline_y, green, s2)
        else:
            draw_score_text(canvas, left_x, baseline_y, white, s1)
            draw_score_text(canvas, team2_x, baseline_y, white, s2)

    def draw_logos(canvas, team1_logo_path, team2_logo_path):
        logo1 = preload_logo(team1_logo_path).resize((15, 15))
        logo2 = preload_logo(team2_logo_path).resize((15, 15))
        canvas.SetImage(logo1, 1, 1, False)
        canvas.SetImage(logo2, 48, 1, False)

    def draw_diagonal(canvas, team1, team2, show_projection=False):
        # Mirrored two-row team blocks with two-pixel outer margins and gaps.
        canvas.SetImage(preload_logo(team1['logo']).resize((12, 12)), 2, 2, False)
        canvas.SetImage(preload_logo(team2['logo']).resize((12, 12)), 50, 18, False)
        for team, side, x, y in ((team1, 1, 16, 9), (team2, 2, 2, 18)):
            name = team.get('name')
            tile = name_renderer.team_window(name, width=46, right_align=(side == 2))
            canvas.SetImage(tile, x, y, False)

        points1 = team1.get("projection") if show_projection else team1["points"]
        points2 = team2.get("projection") if show_projection else team2["points"]
        points1 = team1["points"] if points1 is None else points1
        points2 = team2["points"] if points2 is None else points2
        color1 = green if points1 > points2 else red if points1 < points2 else white
        color2 = green if points2 > points1 else red if points2 < points1 else white
        score1 = display_points(team1, show_projection)
        score2 = display_points(team2, show_projection)
        # Scores use a larger bold 5x7 treatment. Team 2 hugs its logo-side edge.
        right_width = sum(score_font.CharacterWidth(ord(char)) for char in score2) + 1
        draw_score_text(canvas, 16, 7, color1, score1)
        draw_score_text(canvas, 48 - right_width, 31, color2, score2)

    def display_scores(canvas, display_league):
        """Render complete frames; queue TD interrupts without advancing rotation."""
        nonlocal display_week, season_type
        monitor = None
        projection_monitor = None
        try:
            print("Press CTRL-C to stop.")
            matchup_data = get_team_data(display_league, display_week)

            def rebuild(data):
                for matchup in data:
                    for side, team in matchup.items():
                        key = f"{team['name']}_{1 if side == 'team1' else 2}"
                        scroll_offsets.setdefault(key, 0)
                        scroll_widths[key] = name_renderer.text_width(team['name'])
                return [(m["team1"], m["team2"]) for m in data]

            screens = rebuild(matchup_data)
            current_screen_index = 0
            celebration_renderer = CelebrationRenderer(name_renderer)
            celebrations = CelebrationQueue(touchdown_duration)
            monitor = create_touchdown_monitor(league_id, display_week, touchdown_poll_interval)
            projection_monitor = LiveProjectionMonitor(
                league_id, display_week, data_refresh_interval)
            projection_version = 0
            last_tick = time.monotonic()
            last_refresh_time = last_tick
            last_frame_time = last_tick - 1
            last_scroll_time = last_tick
            rotation_elapsed = 0
            was_celebrating = False

            while True:
                now = time.monotonic()
                delta = max(0, now - last_tick)
                last_tick = now
                resumed = was_celebrating
                if not was_celebrating:
                    rotation_elapsed += delta
                redraw = resumed
                events = monitor.events(display_week, now)
                projection_totals, current_projection_version = projection_monitor.totals(display_week)
                if current_projection_version != projection_version:
                    for matchup in matchup_data:
                        for team in matchup.values():
                            team["projection"] = projection_totals.get(team["roster_id"])
                    screens = rebuild(matchup_data)
                    projection_version = current_projection_version
                    redraw = True
                for event in events:
                    logger.info("Queued %s: %s", event.kind, event.name)
                celebration = celebrations.step(now, events)
                if celebration is not None:
                    event, elapsed = celebration
                    canvas.SetImage(celebration_renderer.render(event, elapsed, touchdown_duration), 0, 0, False)
                    canvas = matrix.SwapOnVSync(canvas)
                    was_celebrating = True
                    # Freeze name offsets and the matchup rotation while celebrating.
                    last_scroll_time = now
                    time.sleep(0.05)
                    continue
                was_celebrating = False

                # Network-heavy legacy matchup refresh is deferred until the
                # celebration queue is empty; the TD worker continues polling.
                if now - last_refresh_time >= data_refresh_interval:
                    previous_week = display_week
                    try:
                        current_week, season_type = get_current_nfl_state()
                        if week_is_dynamic:
                            display_week = current_week
                    except (requests.RequestException, ValueError) as error:
                        logger.warning("Could not refresh NFL state: %s", error)
                    try:
                        matchup_data = get_team_data(display_league, display_week)
                        for matchup in matchup_data:
                            for team in matchup.values():
                                team["projection"] = projection_totals.get(team["roster_id"])
                        screens = rebuild(matchup_data)
                        current_screen_index = current_screen_index % len(screens) if screens else 0
                        redraw = True
                    except (requests.RequestException, ValueError) as error:
                        logger.warning("Matchup refresh failed; retaining last display: %s", error)
                    if previous_week != display_week:
                        celebrations = CelebrationQueue(touchdown_duration)
                        rotation_elapsed = 0
                    last_refresh_time = time.monotonic()

                if screens and rotation_elapsed >= rotation_interval and not resumed:
                    current_screen_index = (current_screen_index + 1) % len(screens)
                    rotation_elapsed = 0
                    redraw = True
                if (now - last_scroll_time) * 1000 >= SCROLL_STEP_MS:
                    for key in scroll_offsets:
                        overflow = max(0, scroll_widths.get(key, 46) - 46)
                        period = max(1, overflow * 2)
                        scroll_offsets[key] = (scroll_offsets[key] + 1) % period
                    last_scroll_time = now
                if redraw or now - last_frame_time >= SCROLL_STEP_MS / 1000:
                    if screens:
                        canvas.Clear()
                        team1, team2 = screens[current_screen_index]
                        show_projection = bool(projection_totals) and (
                            int(now / PROJECTION_DISPLAY_INTERVAL) % 2 == 1)
                        canvas = draw_matchup(
                            canvas, team1, team2, black, show_projection)
                        canvas = matrix.SwapOnVSync(canvas)
                    else:
                        canvas = draw_empty_screen(canvas)
                    last_frame_time = now
                time.sleep(0.05)
        except KeyboardInterrupt:
            sys.exit(0)
        finally:
            if monitor is not None:
                monitor.close()
            if projection_monitor is not None:
                projection_monitor.close()

    # Start displaying scores
    display_scores(canvas, my_league)

if __name__ == "__main__":
    main()
