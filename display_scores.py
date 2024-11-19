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
        font = graphics.Font()
        font.LoadFont("rpi-rgb-led-matrix/fonts/7x13B.bdf")  # Adjust font path if needed
    except IOError:
        print(f"Error loading font: {e}")

    # Set color to white
    color = graphics.Color(255, 255, 255)

    def get_live_scores():
        """Fetch live scores from Sleeper."""
        try:
            matchups = league.get_matchups(11)
            rosters = league.get_rosters()

            # Log the raw response to see what's being returned
            #print(f"Matchups: {matchups}")
            #print(f"Rosters: {rosters}")

            if not matchups or not rosters:
                raise ValueError("No matchups or teams found. Check your league ID and API access.")

            # Map user IDs to roster_id
            # user_map = {str(roster["owner_id"]): roster["roster_id"] for roster in rosters}

            # Log user_map
            # print(f"User Map: {user_map}")

            scores = []
            for team in matchups:
                # user1 = user_map.get(matchup["roster_id"], "Team 1")
                # user2 = user_map.get(matchup["roster_id"], "Team 2")

                if team:
                    user1_roster_id = team["roster_id"]

                    # Find the opponent in the same matchup_id
                    user2_roster_id = next(
                        (t["roster_id"] for t in matchups if
                         t["matchup_id"] == team["matchup_id"] and t["roster_id"] != user1_roster_id),
                        None
                    )

                    print(f"roster ID {user1_roster_id} VS roster ID {user2_roster_id}")

                    # # Retrieve owner IDs from roster_ids IDs using user_map
                    # user1 = user_map.get(user1_roster_id, "Unknown Team 1")
                    # user2 = user_map.get(user2_roster_id, "Unknown Team 2")

                    user1_score = team["points"]

                    # Find the opponent in the same matchup_id
                    user2_score = next(
                        (t["points"] for t in matchups if
                         t["matchup_id"] == team["matchup_id"] and t["points"] != user1_score),
                        None
                    )

                #    print(f"{user1_roster_id}: {user1_score}, {user2_roster_id}: {user2_score}")

                else:
                    print("Matchup not found.")

                scores.append([[user1_roster_id, user1_score], [user2_roster_id, user2_score]])
               # print(f"scores: {scores}")

            return scores
        except Exception as e:
            # Get the traceback information
            tb = traceback.extract_tb(e.__traceback__)

            # Extract the line number and filename from the last frame
            line_number = tb[-1].lineno
            filename = tb[-1].filename

            print(f"Error fetching scores on line {line_number} in {filename}: {e} ")
            return []

    def display_scores():
        """Display live fantasy football scores on the LED matrix."""
        try:
            print("Press CTRL-C to stop.")

            while True:
                scores = get_live_scores()

                for matchup in scores:
                    # Extract teams and their scores
                    team1_roster_id, team1_score = matchup[0]
                    team2_roster_id, team2_score = matchup[1]

                    # Map roster IDs to user/team names
                    # team1_name = user_map.get(roster_to_owner.get(team1_roster_id, None), f"Team {team1_roster_id}")
                    # team2_name = user_map.get(roster_to_owner.get(team2_roster_id, None), f"Team {team2_roster_id}")

                    # Format text for display
                    text1 = f"{team1_roster_id}: {team1_score:.1f}"
                    text2 = f"{team2_roster_id}: {team2_score:.1f}"

                    print(text1, "\n", text2)
                    matrix.Clear()

                    # Create an image for the matchup
                    # image = Image.new("RGB", (64, 32), "black")  # 64x32 matrix
                    # draw = ImageDraw.Draw(image)
                    graphics.DrawText(matrix, font, 1, 15, color, text1)
                    graphics.DrawText(matrix, font, 1, 30, color, text2)

                    # Display the image on the matrix
                    # matrix.SetImage(image.convert("RGB"))

                    # Wait before showing the next matchup
                    time.sleep(REFRESH_INTERVAL)

        except KeyboardInterrupt:
            sys.exit(0)

    # Start displaying scores
    display_scores()

if __name__ == "__main__":
    main()
