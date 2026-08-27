from logging import getLogger

from pyqtgraph.parametertree import (
    Parameter,
    ParameterItem,
    ParameterTree,
    registerParameterType,
)
from pyqtgraph.parametertree.parameterTypes import WidgetParameterItem
from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QPushButton

from mints_backend.device_manager import (
    DeviceManager,
    Output,
    OutputState,
    Sensor,
    SensorKind,
)

log = getLogger(__name__)

SENSOR_UNITS: dict[SensorKind, str] = {
    SensorKind.Temperature: "°C",
    SensorKind.Pressure: "Pa",
    SensorKind.LoadCell: "N",
}


class OutputButton(QPushButton):
    sigChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self.clicked.connect(self._on_click)
        self.setText("...")
        self.setFixedSize(45, 25)
        self.setCheckable(True)
        self._confirmed_state: bool | None = None
        self.update_style()

    def update_style(self):
        if self._confirmed_state is None:
            bg, fg = "gray", "black"
        elif self._confirmed_state:
            bg, fg = "green", "white"
        else:
            bg, fg = "red", "black"
        self.setStyleSheet(
            f"background-color: {bg}; color: {fg}; margin-left: 5; min-width: 55;"
        )

    @Slot(bool)
    def _on_click(self, is_checked: bool):
        self.sigChanged.emit(is_checked)

    def value(self) -> bool:
        return self.isChecked()

    def setValue(self, value: bool) -> None:
        # Don't set the value any way other than through the backend
        pass


class OutputButtonItem(WidgetParameterItem):
    def __init__(self, param, depth):
        super().__init__(param, depth)
        param.sigUpdateFromBackend.connect(self.set_value_from_backend)

    def makeWidget(self) -> OutputButton:
        self.hideWidget = False
        return OutputButton()

    def makeDefaultButton(self) -> QPushButton:
        # suppress return-to-default button
        btn = QPushButton()
        btn.setFixedSize(0, 0)
        return btn

    def set_value_from_backend(self, value: bool) -> None:
        self.widget._confirmed_state = value
        self.widget.setChecked(value)
        self.widget.setText("Open" if value else "Closed")
        self.widget.update_style()


class OutputParameter(Parameter):
    sigUpdateFromBackend = Signal(bool)

    @property
    def itemClass(self) -> type[ParameterItem]:
        return OutputButtonItem

    def update_from_backend(self, val: bool) -> None:
        self.sigUpdateFromBackend.emit(val)


registerParameterType("output", OutputParameter)


class DeviceParameterTree(ParameterTree):
    def __init__(self, device_manager: DeviceManager, parent=None):
        super().__init__(parent)
        self.device_manager = device_manager
        self._sensor_params: dict[str, Parameter] = {}
        self.root = Parameter.create(name="Devices", type="group", children=[])
        self.setParameters(self.root, showTop=False)
        self._build_tree()

    def _get_or_create_board_group(self, board_id: int) -> Parameter:
        name = f"Board {hex(board_id)}"
        if name in self.root.names:
            return self.root.child(name)
        group = Parameter.create(name=name, type="group", children=[])
        self.root.addChild(group)
        return group

    def _build_tree(self) -> None:
        for dev in self.device_manager.device_registry.values():
            board_id = dev.id >> 4
            board_group = self._get_or_create_board_group(board_id)
            match dev:
                case Output():
                    self._add_output_param(board_group, dev)

                case Sensor():
                    self._add_sensor_param(board_group, dev)

    def _add_output_param(self, board_group: Parameter, dev: Output) -> None:
        param: OutputParameter = Parameter.create(name=dev.name, type="output")  # pyright: ignore[reportAssignmentType]

        def on_param_changed(_param, val: bool, dev=dev) -> None:
            dev.set_state(OutputState.High if val else OutputState.Low)

        @Slot(bool)
        def on_can_rx(val: bool) -> None:
            param.update_from_backend(val)

        dev.add_slot_fn(on_can_rx)
        param.sigValueChanged.connect(on_param_changed)
        board_group.addChild(param)

    def _add_sensor_param(self, board_group: Parameter, dev: Sensor) -> None:
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

        @Slot(int)
        def on_value(val: int) -> None:
            param.setValue(val)

        dev.subscribe(on_value)

    def teardown(self) -> None:
        for dev in self.device_manager.device_registry.values():
            match dev:
                case Sensor():
                    dev.unsubscribe()
                case _:
                    pass
