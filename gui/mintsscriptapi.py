from nexus import BusRider
from gui import GraphView, ExportView, AutoPoller

class MintsScriptAPI():
    def __init__(self, devices: dict[BusRider] = {}, graph: GraphView = None, exporter: ExportView = None, autopoller: AutoPoller = None, abort: callable = None):
        self.devices = devices
        self.graph = graph
        self.exporter = exporter
        self.autopoller = autopoller
        self.abort = abort
