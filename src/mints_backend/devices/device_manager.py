from typing import Dict, List

from config import config as CFG

Valves_t = List[Dict[str, int | str | None]]
AdcCfg_t = Dict[str, int | str | None]


class DeviceManager:
    def __init__(self):
        self._registry: List[Board | None] = []

        for entry in CFG["board"]:
            try:
                board = Board(entry)
            except IndexError as e:
                raise IndexError from e

            self._registry.append(board)


class Board:
    def __init__(self, board):
        try:
            self.node_id: int = board["node_id"]
            self.valves: Valves_t = board["valves"]
            self.adc = Adc(board["adc"])
        except IndexError as e:
            raise IndexError from e


class Adc:
    def __init__(self, adc_cfg: AdcCfg_t):
        self.channels = adc_cfg["channels"]
