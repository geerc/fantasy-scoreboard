import time
import requests
import argparse
import os
import sys
import logging
from PIL import Image
from sleeper_wrapper import League

# --- Configuration: can be set via CLI args or environment variables ---
DEFAULT_LEAGUE_ID = os.getenv("SLEEPER_LEAGUE_ID", "1389341850288009216")
DISPLAY_WEEK_OVERRIDE = os.getenv("DISPLAY_WEEK")
DEFAULT_WEEK = int(DISPLAY_WEEK_OVERRIDE) if DISPLAY_WEEK_OVERRIDE else None
DEFAULT_ROTATION_INTERVAL = int(os.getenv("ROTATION_INTERVAL", "10"))
DEFAULT_DATA_REFRESH_INTERVAL = int(os.getenv("DATA_REFRESH_INTERVAL", "60"))
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


def get_current_nfl_week():
    """Return Sleeper's current NFL week."""
    response = requests.get(SLEEPER_NFL_STATE_URL, timeout=10)
    response.raise_for_status()
    week = response.json().get("week")
    if not isinstance(week, int) or week < 1:
        raise ValueError(f"Sleeper returned an invalid NFL week: {week!r}")
    return week


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

    args = parser.parse_args()

    league_id = args.league_id
    week_is_dynamic = args.week is None
    if args.week is not None:
        display_week = args.week
        logger.info("Displaying configured NFL week %s", display_week)
    else:
        try:
            display_week = get_current_nfl_week()
            logger.info("Sleeper reports the current NFL week as %s", display_week)
        except (requests.RequestException, ValueError) as error:
            display_week = 1
            logger.warning(
                "Could not determine the current NFL week (%s); falling back to week %s",
                error,
                display_week,
            )
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
                    "name": team1_details["team_name"],
                    "wins": team1_details["wins"],
                    "losses": team1_details["losses"],
                    "ties": team1_details["ties"],
                    "points": team1["points"],
                    "logo": team1_logo_file
                },
                "team2": {
                    "name": team2_details["team_name"],
                    "wins": team2_details["wins"],
                    "losses": team2_details["losses"],
                    "ties": team2_details["ties"],
                    "points": team2["points"],
                    "logo": team2_logo_file
                }
            })

        return detailed_matchups

    def draw_matchup(canvas, team1_data, team2_data, bg_color):
        # Draw logos
        draw_logos(team1_data['logo'], team2_data['logo'])

        # Logo positions and widths
        logo1_x = 1
        logo2_x = 33
        name_y = 22
        box_width = 45

        # Draw team names
        draw_static_name(canvas, logo1_x, name_y, box_width=box_width, name=team1_data.get('name'), right_align=False)
        draw_static_name(canvas, logo2_x, name_y, box_width=box_width, name=team2_data.get('name'), right_align=True)

        # Draw scores
        draw_scores(canvas, team1_data['points'], team2_data['points'])

        return canvas

    def draw_empty_screen(canvas):
        """Show a useful placeholder while the league has no scheduled matchups."""
        canvas.Clear()
        graphics.DrawText(canvas, text_font, 2, 12, white, "NO MATCHUPS")
        graphics.DrawText(canvas, text_font, 2, 23, white, f"WEEK {display_week}")
        return matrix.SwapOnVSync(canvas)

    def draw_scores(canvas, team1_score, team2_score):
        left_x = 1
        baseline_y = 31

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

        s1 = str(team1_score)
        s2 = str(team2_score)

        s1_w = text_pixel_width(s1)
        s2_w = text_pixel_width(s2)

        # right-aligned x for team2 (so right-most pixel sits at panel_width - right_margin)
        team2_x = panel_width - right_margin - s2_w

        # Guard against overlap with left team; ensure minimum separation
        min_sep = 14  # minimum pixels between left score x and right score x
        if team2_x <= left_x + min_sep:
            team2_x = left_x + min_sep

        # draw using color rules
        if team1_score > team2_score:
            graphics.DrawText(canvas, score_font, left_x, baseline_y, green, s1)
            graphics.DrawText(canvas, score_font, team2_x, baseline_y, red, s2)
        elif team2_score > team1_score:
            graphics.DrawText(canvas, score_font, left_x, baseline_y, red, s1)
            graphics.DrawText(canvas, score_font, team2_x, baseline_y, green, s2)
        else:
            graphics.DrawText(canvas, score_font, left_x, baseline_y, white, s1)
            graphics.DrawText(canvas, score_font, team2_x, baseline_y, white, s2)

    def draw_logos(team1_logo_path, team2_logo_path):
        logo1 = ""
        logo2 = ""

        # if team1_logo_path is not None:
        #     logo1 = Image.open(team1_logo_path)
        #     logo1 = logo1.resize((20, 20))
        # if team2_logo_path is not None:
        #     logo2 = Image.open(team2_logo_path)
        #     logo2 = logo2.resize((20, 20))

        logo1 = preload_logo(team1_logo_path)
        logo1 = logo1.resize((15, 15))

        logo2 = preload_logo(team2_logo_path)
        logo2 = logo2.resize((15, 15))

        matrix.SetImage(logo1, 1, 1)
        matrix.SetImage(logo2, 48, 1)

        # Draw team logo for both teams
        if logo1:
            matrix.SetImage(logo1.convert('RGB'), 1, 1)
        if logo2:
            matrix.SetImage(logo2.convert('RGB'), 48, 1)

    def draw_static_name(canvas, x, y, box_width, name, right_align=False, px_per_char=6):
        """
        Draw a static team name in a box under a logo.
        - x, y: top-left of box
        - box_width: width in pixels
        - right_align: if True, align text to the right edge
        - px_per_char: approximate width of each character in pixels
        """
        if not name:
            return

        # Calculate text width in pixels
        text_px = len(name) * px_per_char

        # Clip name if too long
        max_chars = box_width // px_per_char
        display_name = name[:max_chars]
        text_px = len(display_name) * px_per_char

        # Determine x position
        if right_align:
            draw_x = x + box_width - text_px  # right-align
        else:
            draw_x = x  # left-align

        # Clear the box first
        text_height = 6  # for 4x6 font
        for col in range(box_width):
            for row in range(y - text_height + 1, y + 1):
                canvas.SetPixel(draw_x + col, row, 0, 0, 0)

        # Draw the name
        graphics.DrawText(canvas, text_font, draw_x, y, white, display_name)

    def display_scores(canvas, display_league):
        """Display live fantasy football scores on the LED matrix."""
        nonlocal display_week
        try:
            print("Press CTRL-C to stop.")

            # --- Initial data fetch ---
            matchup_data = get_team_data(display_league, display_week)

            # Initialize screens
            screens = [
                (team1_key, team1_data, team2_key, team2_data)
                for matchup in matchup_data
                for (team1_key, team1_data), (team2_key, team2_data) in [list(matchup.items())]
            ]

            if not screens:
                logger.info("No matchups are scheduled for week %s", display_week)
                canvas = draw_empty_screen(canvas)

            # Initialize scroll offsets and text widths
            for matchup in matchup_data:
                for side, team in matchup.items():
                    key = f"{team['name']}_{1 if side == 'team1' else 2}"
                    scroll_offsets.setdefault(key, 0)
                    scroll_widths[key] = len(team['name']) * 6  # px_per_char

            # Initialize indexes and timers
            current_screen_index = 0
            last_switch_time = time.time()
            last_refresh_time = time.time()
            last_scroll_time = time.time()

            while True:
                current_time = time.time()

                # --- Advance scrolling offsets ---
                if (current_time - last_scroll_time) * 1000 >= SCROLL_STEP_MS:
                    for key in scroll_offsets.keys():
                        scroll_offsets[key] = scroll_offsets.get(key, 0) + 1
                        wrap_at = scroll_widths.get(key, 100) + 6
                        if scroll_offsets[key] > wrap_at:
                            scroll_offsets[key] = 0
                    last_scroll_time = current_time

                    if screens:
                        # Redraw current screen with updated offsets
                        canvas.Clear()
                        team1_key, team1_data, team2_key, team2_data = screens[current_screen_index]
                        canvas = draw_matchup(canvas, team1_data, team2_data, black)
                        canvas = matrix.SwapOnVSync(canvas)

                # --- Screen rotation ---
                if screens and current_time - last_switch_time >= rotation_interval:
                    current_screen_index = (current_screen_index + 1) % len(screens)
                    last_switch_time = current_time

                    # Draw new screen (scroll offsets preserved)
                    canvas.Clear()
                    team1_key, team1_data, team2_key, team2_data = screens[current_screen_index]
                    canvas = draw_matchup(canvas, team1_data, team2_data, black)
                    canvas = matrix.SwapOnVSync(canvas)

                # --- Data refresh ---
                if current_time - last_refresh_time >= data_refresh_interval:
                    if week_is_dynamic:
                        try:
                            current_week = get_current_nfl_week()
                            if current_week != display_week:
                                logger.info(
                                    "NFL week changed from %s to %s",
                                    display_week,
                                    current_week,
                                )
                                display_week = current_week
                        except (requests.RequestException, ValueError) as error:
                            logger.warning(
                                "Could not refresh the current NFL week; continuing with week %s: %s",
                                display_week,
                                error,
                            )

                    matchup_data = get_team_data(display_league, display_week)

                    # Rebuild screens
                    screens = [
                        (team1_key, team1_data, team2_key, team2_data)
                        for matchup in matchup_data
                        for (team1_key, team1_data), (team2_key, team2_data) in [list(matchup.items())]
                    ]

                    # Ensure offsets for any new team names
                    for matchup in matchup_data:
                        for side, team in matchup.items():
                            key = f"{team['name']}_{1 if side == 'team1' else 2}"
                            scroll_offsets.setdefault(key, 0)
                            scroll_widths.setdefault(key, len(team['name']) * 6)

                    if screens:
                        # Wrap current screen index safely
                        current_screen_index %= len(screens)
                    else:
                        current_screen_index = 0
                        logger.info("No matchups are scheduled for week %s", display_week)
                        canvas = draw_empty_screen(canvas)
                    last_refresh_time = current_time

                # Small sleep to reduce CPU usage
                time.sleep(0.05)

        except KeyboardInterrupt:
            sys.exit(0)

    # Start displaying scores
    display_scores(canvas, my_league)

if __name__ == "__main__":
    main()
