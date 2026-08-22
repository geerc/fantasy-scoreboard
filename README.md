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

The defaults can be overridden with command-line options:

```bash
venv/bin/python main.py --emulator \
  --league-id YOUR_SLEEPER_LEAGUE_ID \
  --week 6 \
  --rotation-interval 10 \
  --data-refresh-interval 60
```

The same defaults can be set with `SLEEPER_LEAGUE_ID`, `DISPLAY_WEEK`,
`ROTATION_INTERVAL`, and `DATA_REFRESH_INTERVAL` environment variables.

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
