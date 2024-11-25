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
3. 
   ```bash
   pip install -r requirements.txt
4. Clone rpi-rgb-led-matrix repository and install Python binding
5. 
   ```bash
    sudo apt-get install -y make
    mkdir submodules
    cd submodules
    git clone https://github.com/hzeller/rpi-rgb-led-matrix.git matrix
   sudo apt-get update && sudo apt-get install python3-dev cython3 -y
   make build-python 
   sudo make install-python 
