from nexus import BusRider
from gui import GraphView, ExportView

class MintsScriptAPI():
    def __init__(self, devices: dict[BusRider] = {}, graph: GraphView = None, exporter: ExportView = None, abort: callable = None):
        self.devices = devices
        self.graph = graph
        self.exporter = exporter
        self.abort = abort
