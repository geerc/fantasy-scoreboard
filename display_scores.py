import time
import requests
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont
from sleeper_wrapper import League

# Replace these with your Sleeper league ID and other details
SLEEPER_LEAGUE_ID = "1116769051939786752"
REFRESH_INTERVAL = 60  # seconds

# Set up the LED matrix options
options = RGBMatrixOptions()
options.rows = 32
options.cols = 64
options.chain_length = 1
options.parallel = 1
options.brightness = 50
options.disable_hardware_pulsing = True  # Disable hardware pulsing to avoid needing root permissions
matrix = RGBMatrix(options=options)

# Set up Sleeper League
league = League(SLEEPER_LEAGUE_ID)

# Load a font
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
except IOError:
    font = ImageFont.load_default()

def get_live_scores():
    """Fetch live scores from Sleeper."""
    try:
        matchups = league.get_matchups(9)
        rosters = league.get_rosters()

	# Log the raw response to see what's being returned
        print(f"Matchups: {matchups}")
        print(f"Rosters: {rosters}")

        if not matchups or not rosters:
            raise ValueError("No matchups or teams found. Check your league ID and API access.")

        # Map user IDs to username
        user_map = {str(roster["user_id"]): roster["display_name"] for roster in rosters}

        # Log user_map
        print(f"User Map: {user_map}")

        scores = []
        for matchup in matchups:
            user1 = user_map.get(matchup["roster_id_1"], "Team 1")
            user2 = user_map.get(matchup["roster_id_2"], "Team 2")
            score1 = matchup["points_1"]
            score2 = matchup["points_2"]
            scores.append(f"{user1}: {score1} vs {user2}: {score2}")

        return scores
    except Exception as e:
        print(f"Error fetching scores: {e}")
        return []

def display_scores():
    """Display live fantasy football scores on the LED matrix."""
    while True:
        scores = get_live_scores()

        # Create an image with the scores to display on the LED matrix
        image = Image.new("RGB", (64, 32), "black")
        draw = ImageDraw.Draw(image)
        y_offset = 0

        for score in scores:
            draw.text((1, y_offset), score, fill="white", font=font)
            y_offset += 12  # Move down to display the next score

        # Display the image on the matrix
        matrix.SetImage(image.convert("RGB"))
        time.sleep(REFRESH_INTERVAL)

if __name__ == "__main__":
    display_scores()
