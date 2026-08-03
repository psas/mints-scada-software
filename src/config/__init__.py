from pathlib import Path
import tomlkit

cfg_path = Path(__file__).parent / "config.toml"
boards_path = Path(__file__).parent / "boards.toml"

with cfg_path.open(mode="rb") as file:
    config = tomlkit.load(file)

with boards_path.open(mode="rb") as file:
    boards = tomlkit.load(file)
