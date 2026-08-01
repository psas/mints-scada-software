from pathlib import Path
import tomlkit

path = Path(__file__).parent / "config.toml"

with path.open(mode="rb") as file:
    config = tomlkit.load(file)
