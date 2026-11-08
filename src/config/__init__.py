import tomllib
from pathlib import Path

cfg_path = Path(__file__).parent / "config.toml"
boards_path = Path(__file__).parent / "boards.toml"

with cfg_path.open(mode="rb") as file:
    config = tomllib.load(file)

with boards_path.open(mode="rb") as file:
    boards = tomllib.load(file)
