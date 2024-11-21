import time
import requests
import argparse
from PIL import Image, ImageSequence
from sleeper_wrapper import League
import traceback

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
        #    options.pwm_lsb_nanoseconds = 130  # Improve LED refresh quality
        matrix = RGBMatrix(options=options)

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
        #    options.disable_hardware_pulsing = False  # Disable hardware pulsing to avoid needing root permissions
        #    options.pwm_lsb_nanoseconds = 130  # Improve LED refresh quality
        matrix = RGBMatrix(options=options)

    # Set up Sleeper League
    league = League(SLEEPER_LEAGUE_ID)

    # Load a font
    try:
        # Load a font
        text_font = graphics.Font()
        text_font.LoadFont("rpi-rgb-led-matrix/fonts/4x6.bdf")  # Adjust font path if needed

        score_font = graphics.Font()
        score_font.LoadFont("rpi-rgb-led-matrix/fonts/6x9.bdf")
    except IOError:
        print(f"Error loading font: {e}")

    # Set color to white
    white = graphics.Color(255, 255, 255)
    red = graphics.Color(255, 0, 0)
    green = graphics.Color(0, 255, 0)

    # pull weekly matchups
    matchups = league.get_matchups(11)

    def get_team_data(league, matchups):
        """Retrieve detailed team data for each matchup."""
        users = league.get_users()  # List of users with 'user_id' and 'display_name'
        rosters = league.get_rosters()  # List of rosters with 'owner_id', 'roster_id', 'wins', 'losses', 'ties'

        # Create a map for user_id to team_name (fallback to display_name if team_name is not set)
        user_map = {
            user["user_id"]: user["metadata"].get("team_name", user["display_name"])
            for user in users
        }

        # Create a mapping of roster_id to team stats
        roster_map = {
            roster['roster_id']: {
                'team_name': user_map.get(roster['owner_id'], "Unknown Team"),
                'wins': roster['settings']['wins'],
                'losses': roster['settings']['losses'],
                'ties': roster['settings']['ties'],
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

            print('team1_details:\n', team1_details)

            detailed_matchups.append({
                "team1": {
                    "name": team1_details["team_name"],
                    "wins": team1_details["wins"],
                    "losses": team1_details["losses"],
                    "ties": team1_details["ties"],
                    "points": team1["points"]
                },
                "team2": {
                    "name": team2_details["team_name"],
                    "wins": team2_details["wins"],
                    "losses": team2_details["losses"],
                    "ties": team2_details["ties"],
                    "points": team2["points"]
                }
            })

        return detailed_matchups

    def display_scores(matchups):
        """Display live fantasy football scores on the LED matrix."""
        try:
            print("Press CTRL-C to stop.")

            while True:
                detailed_matchups = get_team_data(league, matchups)

                for matchup in detailed_matchups:
                    team1 = matchup["team1"]  # Access 'team1' key from the matchup dictionary
                    team2 = matchup["team2"]  # Access 'team2' key from the matchup dictionary

                    team_name1 = f"{team1['name']}"
                    team_name2 = f"{team2['name']}"

                    record1 = f"({team1['wins']}-{team1['losses']})"
                    record2 = f"({team2['wins']}-{team2['losses']})"

                    score1 = f"{team1['points']}"
                    score2 = f"{team2['points']}"

                    # Clear the screen
                    matrix.Clear()

                    # Draw text for both teams
                    graphics.DrawText(matrix, text_font, 1, 6, white, team_name1)
                    graphics.DrawText(matrix, text_font, 1, 12, white, record1)

                    graphics.DrawText(matrix, text_font, 1, 31, white, record2)
                    graphics.DrawText(matrix, text_font, 1, 22, white, team_name2)

                    if team1['points'] > team2['points']:
                        graphics.DrawText(matrix, score_font, 28, 15, green, score1)
                        graphics.DrawText(matrix, score_font, 28, 31, red, score2)
                    elif team2['points'] > team1['points']:
                        graphics.DrawText(matrix, score_font, 28, 15, red, score1)
                        graphics.DrawText(matrix, score_font, 28, 31, green, score2)
                    else:
                        graphics.DrawText(matrix, score_font, 28, 15, white, score1)
                        graphics.DrawText(matrix, score_font, 28, 31, white, score2)

                    # Wait before showing the next matchup
                    time.sleep(REFRESH_INTERVAL)

        except KeyboardInterrupt:
            sys.exit(0)

    # Start displaying scores
    display_scores(matchups)

if __name__ == "__main__":
    main()
