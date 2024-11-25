import time

import requests
import argparse
from PIL import Image, ImageSequence
from sleeper_wrapper import League
import traceback
import os

# Replace these with your Sleeper league ID and other details
SLEEPER_LEAGUE_ID = "1116769051939786752"
REFRESH_INTERVAL = 10  # seconds

def main():
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(description="Run LED board with optional emulator.")
    parser.add_argument(
        '--emulator',
        type=bool,
        default=False,
        help="Set to True to use the RGBMatrixEmulator instead of RGBMatrix."
    )
    args = parser.parse_args()

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
    my_league = League(SLEEPER_LEAGUE_ID)
    week = 12

    # Load a font
    try:
        # Load a font
        text_font = graphics.Font()
        text_font.LoadFont("rpi-rgb-led-matrix/fonts/4x6.bdf")  # Adjust font path if needed

        score_font = graphics.Font()
        score_font.LoadFont("rpi-rgb-led-matrix/fonts/5x7.bdf")
    except IOError:
        print(f"Error loading font: {e}")

    # Set colors
    white = graphics.Color(255, 255, 255)
    red = graphics.Color(255, 0, 0)
    green = graphics.Color(0, 255, 0)
    black = graphics.Color(0, 0, 0)

    def get_team_data(data_league, week):
        """Retrieve detailed team data for each matchup."""

        # pull weekly matchups
        matchups = data_league.get_matchups(week)

        users = data_league.get_users()  # List of users with 'user_id' and 'display_name'
        rosters = data_league.get_rosters()  # List of rosters with 'owner_id', 'roster_id', 'wins', 'losses', 'ties'

        # Create the 'logos' directory in the current working directory
        logos_dir = os.path.join(os.getcwd(), "logos")  # Constructs the path for 'logos' in the current directory
        os.makedirs(logos_dir, exist_ok=True)  # Creates the directory if it doesn't already exist

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

    def draw_matchup(canvas, pos_1, pos_2, team1_data, team2_data, bg_color):
        # Draw logos
        draw_logos(team1_data['logo'], team2_data['logo'])

        # Draw scores for both teams
        draw_scores(team1_data['points'], team2_data['points'])

        return canvas

    def draw_scores(team1_score, team2_score):
        # Draw team scores and records (static text)
        if team1_score > team2_score:
            graphics.DrawText(matrix, score_font, 1, 31, green, str(team1_score))
            graphics.DrawText(matrix, score_font, 35, 31, red, str(team2_score))
        elif team2_score > team1_score:
            graphics.DrawText(matrix, score_font, 1, 31, red, str(team1_score))
            graphics.DrawText(matrix, score_font, 35, 31, green, str(team2_score))
        else:
            graphics.DrawText(matrix, score_font, 1, 31, white, str(team1_score))
            graphics.DrawText(matrix, score_font, 35, 31, white, str(team2_score))

        # graphics.DrawText(matrix, text_font, 1, 12, white, record1)
        # graphics.DrawText(matrix, text_font, 1, 31, white, record2)


    def draw_logos(team1_logo_path, team2_logo_path):
        logo1 = ""
        logo2 = ""

        if team1_logo_path is not None:
            logo1 = Image.open(team1_logo_path)
            logo1 = logo1.resize((20, 20))
        if team2_logo_path is not None:
            logo2 = Image.open(team2_logo_path)
            logo2 = logo2.resize((20, 20))

        # Draw team logo for both teams
        if logo1:
            matrix.SetImage(logo1.convert('RGB'), 1, 1)
        if logo2:
            matrix.SetImage(logo2.convert('RGB'), 44, 1)

    def display_scores(canvas, display_league):
        """Display live fantasy football scores on the LED matrix."""
        try:
            print("Press CTRL-C to stop.")

            display_week = 11

            # Initial data fetch and processing
            matchup_data = get_team_data(display_league, display_week)

            # Initialize position of the text
            pos_1 = 15
            pos_2 = 15

            print(f'Data: {matchup_data}')
            print('Matchups')
            for matchup in matchup_data:
                print(matchup)

            # Create a list of screens dynamically based on the provided data
            screens = [
                (team1_key, team1_data, team2_key, team2_data)
                for matchup in matchup_data
                for (team1_key, team1_data), (team2_key, team2_data) in [list(matchup.items())]
            ]

            # Initialize screen index
            current_screen_index = 0

            # Rotation interval between screens in seconds
            rotation_interval = 10

            # Time tracking
            last_switch_time = time.time()
            data_refresh_interval = 60
            last_refresh_time = time.time()

            while True:
                current_time = time.time()

                # Check if it's time to refresh the data and logos
                if current_time - last_refresh_time >= data_refresh_interval:
                    matchup_data = get_team_data(display_league, display_week)

                    # Create a list of screens dynamically based on the provided data
                    screens = [
                        (team1_key, team1_data, team2_key, team2_data)
                        for matchup in matchup_data
                        for (team1_key, team1_data), (team2_key, team2_data) in [list(matchup.items())]
                    ]

                    # reset last refresh time
                    last_refresh_time = current_time

                # Check if it's time to switch the screen
                if current_time - last_switch_time >= rotation_interval:
                    canvas.Clear()

                    current_screen_index = (current_screen_index + 1) % len(screens)
                    last_switch_time = current_time

                # Unpack current screen data
                team1_key, team1_data, team2_key, team2_data = screens[current_screen_index]

                # Draw the current matchups's screen with the scrolling text
                canvas = draw_matchup(canvas, pos_1, pos_2, team1_data, team2_data, black)

                # Swap the canvas to update the display
                canvas = matrix.SwapOnVSync(canvas)

        except KeyboardInterrupt:
            sys.exit(0)

    # Start displaying scores
    display_scores(canvas, my_league)

if __name__ == "__main__":
    main()
