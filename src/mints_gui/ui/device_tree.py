from logging import getLogger
from typing import Dict

from pyqtgraph.parametertree import (
    Parameter,
    ParameterItem,
    ParameterTree,
    registerParameterType,
)
from pyqtgraph.parametertree.parameterTypes import WidgetParameterItem
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QSizePolicy, QToolButton

from mints_backend.device_manager import (
    DeviceManager,
    Output,
    OutputState,
    Sensor,
    SensorKind,
)

log = getLogger(__name__)

SENSOR_UNITS: Dict[SensorKind, str] = {
    SensorKind.Temperature: "°C",
    SensorKind.Pressure: "Pa",
    SensorKind.LoadCell: "N",
}


class OutputButton(QToolButton):
    sigChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.toggled.connect(self._on_toggled)
        self.setText("Closed")
        self.setFixedSize(45, 25)
        self.setStyleSheet(
            "background-color: red; color: black; margin-left: 5; min-width: 55;"
        )

    def _on_toggled(self, checked: bool):
        self.setText("Open" if checked else "Closed")
        styles = self.styleSheet()
        print(styles)
        self.setStyleSheet(
            styles
            + (
                "background-color: green; color: white;"
                if checked
                else "background-color: red; color: black;"
            )
        )
        self.sigChanged.emit(checked)

    def value(self) -> bool:
        return self.isChecked()

    def setValue(self, val: bool):
        self.blockSignals(True)
        self.setChecked(val)
        self.blockSignals(False)


class OutputButtonItem(WidgetParameterItem):
    def makeWidget(self):
        self.hideWidget = False
        return OutputButton()


class OutputParameter(Parameter):
    @property
    def itemClass(self) -> type[ParameterItem]:
        return OutputButtonItem


registerParameterType("output", OutputParameter)


class DeviceParameterTree(ParameterTree):
    def __init__(self, device_manager: DeviceManager, parent=None):
        super().__init__(parent)
        self.device_manager = device_manager
        self._sensor_params: Dict[str, Parameter] = {}

        self.root = Parameter.create(name="Devices", type="group", children=[])
        self.setParameters(self.root, showTop=False)

        self._build_tree()

    def _get_or_create_board_group(self, node_id: int) -> Parameter:
        name = f"Board {hex(node_id)}"
        if name in self.root.names:
            return self.root.child(name)
        group = Parameter.create(name=name, type="group", children=[])
        self.root.addChild(group)
        return group

    def _build_tree(self):
        for dev in self.device_manager.device_registry.values():
            node_id = dev.id >> 4
            board_group = self._get_or_create_board_group(node_id)

            match dev:
                case Output():
                    self._add_output_param(board_group, dev)

                case Sensor():
                    self._add_sensor_param(board_group, dev)

    def _add_output_param(self, board_group: Parameter, dev: Output):
        param = Parameter.create(name=dev.name, type="output")

        def on_param_changed(_param, val: bool, dev=dev):

            print("setting state")
            dev.set_state(OutputState.High if val else OutputState.Low)

        param.sigValueChanged.connect(on_param_changed)
        board_group.addChild(param)

    def _add_sensor_param(self, board_group: Parameter, dev: Sensor):
        unit = SENSOR_UNITS.get(dev.kind, "")
        param = Parameter.create(
            name=dev.name,
            type="float",
            value=0.0,
            suffix=unit,
            readonly=True,
            tip=f"{dev.kind.value} sensor (id=0b{dev.id:b})",
        )
        board_group.addChild(param)
        self._sensor_params[dev.name] = param

        def on_value(val, p=param):
            p.setValue(val)

        dev.subscribe(on_value)

    def teardown(self):
        for dev in self.device_manager.device_registry.values():
            match dev:
                case Sensor():
                    dev.unsubscribe()
                case _:
                    pass
