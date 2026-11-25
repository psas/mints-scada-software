# mints-scada-software

## Getting Started

### Install Qt Dependencies

```sh
sudo apt install \
  libfontconfig1-dev \
  libfreetype-dev \
  libgtk-3-dev \
  libx11-dev \
  libx11-xcb-dev \
  libxcb-cursor-dev \
  libxcb-glx0-dev \
  libxcb-icccm4-dev \
  libxcb-image0-dev \
  libxcb-keysyms1-dev \
  libxcb-randr0-dev \
  libxcb-render-util0-dev \
  libxcb-shape0-dev \
  libxcb-shm0-dev \
  libxcb-sync-dev \
  libxcb-util-dev \
  libxcb-xfixes0-dev \
  libxcb-xkb-dev \
  libxcb1-dev \
  libxext-dev \
  libxfixes-dev \
  libxi-dev \
  libxkbcommon-dev \
  libxkbcommon-x11-dev \
  libxrender-dev
```

### Virtual Environment

Create the venv
```sh
python3 -m venv .venv
```

Activate the venv
```sh
source .venv/bin/activate
```

Install python packages
```sh
pip install -e .
```

Install dev packages
```sh
pip install --group=dev
```

If you have [uv](https://docs.astral.sh/uv/) installed, you can skip the steps below "Virtual Environment" and simply do:

```sh
uv run mints-gui
```

## Virtual CAN Interface
To easily run tests or use the mock firmware in `scripts/mock_firmware.py`, set up a virtual CAN interface on your machine:

```sh
sudo ip link add vcan0 type vcan && sudo ip link set up vcan0
```

## Running Tests
To run the test suite:

```sh
pytest
```
or with `uv`,

```sh
uv run pytest
```

## Running the Mock Firmware
To run the mock firmware:

```sh
python3 -m scripts.mock_firmware
```

or with `uv`,

```sh
uv run scripts/mock_firmware.py
```
