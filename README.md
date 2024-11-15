# Fantasy Football Live Scores on 64x32 LED Matrix

This Python program fetches live fantasy football scores from a Sleeper league and displays them on a 64x32 LED matrix connected to a Raspberry Pi.

## Requirements

- Raspberry Pi (configured with a 64x32 RGB LED matrix)
- Python 3.x
- Sleeper API account and league ID
- Internet connection for live score fetching

## Setup

1. Clone this repository and navigate to the project folder.
2. Install the required packages:
   ```bash
   pip install -r requirements.txt
3. sudo apt-get install -y make
    mkdir submodules
    cd submodules
    git clone https://github.com/hzeller/rpi-rgb-led-matrix.git matrix
    cd matrix
    # Checkout the branch or commit specified for rpi-rgb-led-matrix
    git checkout $DRIVER_SHA
    git pull
    make build-python PYTHON="$PYTHON"
    sudo make install-python PYTHON="$PYTHON"
