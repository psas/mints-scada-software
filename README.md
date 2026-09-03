# mints-scada-software

## Getting Started
This sofware was developed using [uv](https://docs.astral.sh/uv/), and instructions will be provided with that in mind.
However, this is not necessarily a requirement, and your preferred virtual environment manager probably works too.

With `uv` installed, simply do:

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
uv run pytest
```

## Running the Mock Firmware
To run the mock firmware:

```sh
uv run scripts/mock_firmware.py
```
