# controller_window.py
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QPainter, QPen, QColor, QDrag
from PyQt5.QtCore import Qt, QTimer, QRect, pyqtSignal, QMimeData, QSize

import qdarkstyle
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from logging import log

from gui import (
    GraphView,
    ExportView,
    ConsoleView,
    ScriptView,
    MintsScriptAPI,
    AutoPollerRow,
    LiveGraphDataProvider,
    PlaybackGraphDataProvider,
    LiveTelemetryPoller,
)
from gui.timelineview import TimelineView
from nexus import BusRider
from settings import SYSTEM_ORDER


DEVICE_MIME_TYPE = "application/x-mints-device-id"
_SYSTEM_ORDER_MAP = {system: idx for idx, system in enumerate(SYSTEM_ORDER)}


def normalize_systems(device_systems):
    if not device_systems:
        return []

    seen = set()
    ordered = []
    for s in device_systems:
        if s and s not in seen:
            seen.add(s)
            ordered.append(s)

    ordered.sort(key=lambda s: (_SYSTEM_ORDER_MAP.get(s, 999), s))
    return ordered


def classify_system_bucket(device_systems):
    systems = normalize_systems(device_systems)

    if not systems:
        return "Unassigned", None
    if len(systems) == 1:
        return systems[0], None

    combo = " + ".join(systems)
    return "Cross-System", combo


@dataclass
class GraphCardState:
    title: str = "Signal Graph"
    device_ids: list[str] = field(default_factory=list)
    duration_s: int = 60


class CollapsibleSection(QFrame):
    expandedChanged = pyqtSignal(bool)
    preferredHeightChanged = pyqtSignal()

    def __init__(
        self, title: str, content_widget: QWidget, expanded: bool = True, parent=None
    ):
        super().__init__(parent)

        self.content_widget = content_widget

        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.setStyleSheet(
            """
            QFrame {
                background: transparent;
                border: 1px solid #3f3f3f;
                border-radius: 8px;
            }
            QToolButton {
                background: transparent;
                color: #f0f0f0;
                border: none;
                font-weight: 700;
                font-size: 13px;
                padding: 6px 8px;
                text-align: left;
                border-radius: 7px;
            }
            QToolButton:hover {
                background: #2a2d2e;
            }
        """
        )

        self.toggle_btn = QToolButton()
        self.toggle_btn.setText(title)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(expanded)
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle_btn.toggled.connect(self._on_toggled)

        self.content_frame = QFrame()
        self.content_frame.setFrameShape(QFrame.NoFrame)
        self.content_frame.setStyleSheet(
            """
            QFrame {
                background: transparent;
                border: none;
            }
        """
        )

        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(6, 0, 6, 6)
        content_layout.setSpacing(0)
        content_layout.addWidget(content_widget)

        self.layout_main = QVBoxLayout(self)
        self.layout_main.setContentsMargins(0, 0, 0, 0)
        self.layout_main.setSpacing(0)
        self.layout_main.addWidget(self.toggle_btn, 0)
        self.layout_main.addWidget(self.content_frame, 0)

        if hasattr(content_widget, "preferredHeightChanged"):
            content_widget.preferredHeightChanged.connect(
                self.preferredHeightChanged.emit
            )

        self._on_toggled(expanded)

    def _on_toggled(self, checked: bool):
        self.content_frame.setVisible(checked)
        self.toggle_btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.updateGeometry()
        self.expandedChanged.emit(checked)
        self.preferredHeightChanged.emit()

    def set_expanded(self, expanded: bool):
        self.toggle_btn.setChecked(expanded)

    def is_expanded(self) -> bool:
        return self.toggle_btn.isChecked()

    def header_height(self) -> int:
        return self.toggle_btn.sizeHint().height()

    def content_vertical_padding(self) -> int:
        m = self.content_frame.layout().contentsMargins()
        return m.top() + m.bottom()

    def preferred_content_height(self) -> int:
        if hasattr(self.content_widget, "preferred_height"):
            return int(self.content_widget.preferred_height())
        return int(self.content_widget.sizeHint().height())

    def set_content_height_limit(self, max_height=None):
        if hasattr(self.content_widget, "set_height_limit"):
            self.content_widget.set_height_limit(max_height)
        else:
            if max_height is None:
                self.content_widget.setMaximumHeight(16777215)
            else:
                self.content_widget.setMaximumHeight(max(0, int(max_height)))
        self.updateGeometry()


class DeviceSectionTree(QTreeWidget):
    deviceActivated = pyqtSignal(str)
    preferredHeightChanged = pyqtSignal()

    def __init__(self, parent=None, allow_drag=False, include_control_bucket=False):
        super().__init__(parent)
        self.allow_drag = allow_drag
        self.include_control_bucket = include_control_bucket
        self._device_items = {}

        self._height_limit = None
        self._preferred_height = 8

        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setDragEnabled(allow_drag)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.setStyleSheet(
            """
            QTreeWidget {
                background: transparent;
                color: #e6e6e6;
                border: none;
                outline: 0;
                padding: 4px 2px 4px 2px;
            }
            QTreeWidget::item {
                padding: 2px 4px;
            }
            QTreeWidget::item:selected {
                background: #264f78;
                color: white;
                border: none;
            }
        """
        )

        self.itemExpanded.connect(
            lambda _item: QTimer.singleShot(0, self.update_height_to_contents)
        )
        self.itemCollapsed.connect(
            lambda _item: QTimer.singleShot(0, self.update_height_to_contents)
        )

    def _append_child(self, parent_item, child_item):
        if parent_item is None:
            self.addTopLevelItem(child_item)
        else:
            parent_item.addChild(child_item)

    def _get_or_create_child(self, parent_item, label: str, cache: dict, bold=False):
        parent_key = id(parent_item) if parent_item is not None else 0
        key = (parent_key, label)
        if key in cache:
            return cache[key]

        item = QTreeWidgetItem([label])
        item.setExpanded(True)

        font = item.font(0)
        font.setBold(bold)
        item.setFont(0, font)

        self._append_child(parent_item, item)
        cache[key] = item
        return item

    def _group_chain_for_meta(self, meta: dict, group_mode: str):
        system_label, combo_label = classify_system_bucket(
            meta.get("deviceSystems", [])
        )
        device_group = meta.get("deviceGroup", "Other")
        device_type = meta.get("deviceType", "Other")

        if group_mode == "Device Group":
            chain = [device_group, system_label]
            if combo_label:
                chain.append(combo_label)
            return chain

        if group_mode == "Device Type":
            chain = [device_type, system_label]
            if combo_label:
                chain.append(combo_label)
            return chain

        chain = [system_label]
        if combo_label:
            chain.append(combo_label)
        chain.append(device_group)
        return chain

    def _iter_visible_items(self):
        def walk(item):
            yield item
            if item.isExpanded():
                for i in range(item.childCount()):
                    yield from walk(item.child(i))

        for i in range(self.topLevelItemCount()):
            yield from walk(self.topLevelItem(i))

    def preferred_height(self) -> int:
        visible_items = list(self._iter_visible_items())

        if not visible_items:
            return 8

        row_h = self.sizeHintForRow(0)
        if row_h <= 0:
            row_h = max(self.fontMetrics().height() + 8, 20)

        return len(visible_items) * row_h + 8

    def _apply_height_limit(self):
        target = max(8, int(self._preferred_height))

        if self._height_limit is None or target <= self._height_limit:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.setFixedHeight(target)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.setFixedHeight(max(24, int(self._height_limit)))

    def update_height_to_contents(self):
        new_pref = self.preferred_height()
        if new_pref != self._preferred_height:
            self._preferred_height = new_pref
            self.preferredHeightChanged.emit()

        self._apply_height_limit()

    def set_height_limit(self, max_height=None):
        normalized = None if max_height is None else max(24, int(max_height))
        if normalized == self._height_limit:
            return
        self._height_limit = normalized
        self._apply_height_limit()

    def populate(self, metas: list, group_mode: str):
        self.clear()
        self._device_items = {}
        cache = {}

        sorted_metas = sorted(
            metas,
            key=lambda m: (
                0 if m.get("isControllable", False) else 1,
                (m.get("name") or "").lower(),
                (m.get("id") or "").lower(),
            ),
        )

        for meta in sorted_metas:
            parent_item = None

            if self.include_control_bucket:
                control_label = (
                    "Controllable"
                    if meta.get("isControllable", False)
                    else "Monitor Only"
                )
                parent_item = self._get_or_create_child(
                    parent_item, control_label, cache, bold=True
                )

            for label in self._group_chain_for_meta(meta, group_mode):
                parent_item = self._get_or_create_child(
                    parent_item, label, cache, bold=(parent_item is None)
                )

            item = QTreeWidgetItem([meta["name"]])
            item.setData(0, Qt.UserRole, meta["id"])
            item.setToolTip(
                0,
                "\n".join(
                    [
                        f"id: {meta['id']}",
                        f"name: {meta['name']}",
                        f"deviceType: {meta['deviceType']}",
                        f"deviceGroup: {meta['deviceGroup']}",
                        f"deviceSystems: {', '.join(normalize_systems(meta.get('deviceSystems', []))) or 'Unassigned'}",
                        (
                            f"address: {meta['address']:#05x}"
                            if isinstance(meta["address"], int)
                            else f"address: {meta['address']}"
                        ),
                        f"hasElectricalIO: {meta['hasElectricalIO']}",
                        f"isControllable: {meta['isControllable']}",
                        f"widgetType: {meta['widgetType']}",
                        f"isActive: {meta['isActive']}",
                    ]
                ),
            )
            self._append_child(parent_item, item)
            self._device_items[meta["id"]] = item

        self.collapseAll()
        self.expandToDepth(0)
        QTimer.singleShot(0, self.update_height_to_contents)

    def jump_to_device(self, device_id: str) -> bool:
        item = self._device_items.get(device_id)
        if item is None:
            return False

        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()

        self.setCurrentItem(item)
        self.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        self.setFocus()
        QTimer.singleShot(0, self.update_height_to_contents)
        return True

    def startDrag(self, supportedActions):
        if not self.allow_drag:
            return

        item = self.currentItem()
        if item is None:
            return

        device_id = item.data(0, Qt.UserRole)
        if not device_id:
            return

        mime = QMimeData()
        mime.setData(DEVICE_MIME_TYPE, str(device_id).encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec_(Qt.CopyAction)

    def mouseDoubleClickEvent(self, event):
        if not self.allow_drag:
            super().mouseDoubleClickEvent(event)
            return

        item = self.itemAt(event.pos())
        if item is not None:
            device_id = item.data(0, Qt.UserRole)
            if device_id:
                self.deviceActivated.emit(str(device_id))
        super().mouseDoubleClickEvent(event)


class DeviceLibraryPanel(QWidget):
    deviceActivated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._all_meta_by_id = {}
        self._group_mode = "System"
        self._reflow_pending = False
        self._last_toggled_section = None

        self.active_signal_tree = DeviceSectionTree(
            allow_drag=True, include_control_bucket=True
        )
        self.active_mechanical_tree = DeviceSectionTree(
            allow_drag=False, include_control_bucket=False
        )
        self.inactive_tree = DeviceSectionTree(
            allow_drag=False, include_control_bucket=False
        )

        self.active_signal_tree.deviceActivated.connect(self.deviceActivated.emit)

        # ----- Search + sort controls -----
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search devices...")
        self.search_input.textChanged.connect(self._update_search_results)
        self.search_input.returnPressed.connect(self._activate_first_search_result)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["System", "Device Group", "Device Type"])
        self.sort_combo.currentTextChanged.connect(self._on_group_mode_changed)
        self.sort_combo.setStyleSheet(
            """
            QComboBox {
                background: #1f1f1f;
                color: #e6e6e6;
                border: 1px solid #4a4a4a;
                border-radius: 6px;
                padding: 4px 8px;
                min-height: 26px;
            }
            QComboBox:hover {
                border: 1px solid #5a5a5a;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
                background: transparent;
            }
            QComboBox QAbstractItemView {
                background: #1b1b1b;
                color: #e6e6e6;
                border: 1px solid #4a4a4a;
                selection-background-color: #3b6ea5;
                selection-color: white;
                outline: 0;
            }
        """
        )

        self.search_input.setStyleSheet(
            """
            QLineEdit {
                background: #1f1f1f;
                color: #e6e6e6;
                border: 1px solid #4a4a4a;
                border-radius: 6px;
                padding: 4px 8px;
                min-height: 26px;
            }
            QLineEdit:focus {
                border: 1px solid #3b6ea5;
            }
        """
        )

        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

        sort_row = QWidget()
        sort_row_layout = QHBoxLayout(sort_row)
        sort_row_layout.setContentsMargins(0, 0, 0, 0)
        sort_row_layout.setSpacing(8)
        sort_row_layout.addWidget(QLabel("Sort by:"), 0)
        sort_row_layout.addWidget(self.sort_combo, 1)

        search_row = QWidget()
        search_row_layout = QHBoxLayout(search_row)
        search_row_layout.setContentsMargins(0, 0, 0, 0)
        search_row_layout.setSpacing(8)
        search_row_layout.addWidget(self.search_input, 1)

        controls_layout.addWidget(sort_row)
        controls_layout.addWidget(search_row)

        self.search_results = QListWidget()
        self.search_results.hide()
        self.search_results.setMaximumHeight(140)
        self.search_results.itemClicked.connect(self._on_search_result_clicked)
        self.search_results.setStyleSheet(
            """
            QListWidget {
                background: #171717;
                color: #e6e6e6;
                border: 1px solid #444;
                border-radius: 6px;
            }
            QListWidget::item:selected {
                background: #3b6ea5;
                color: white;
            }
        """
        )

        self.search_empty_label = QLabel("No matched device found")
        self.search_empty_label.hide()
        self.search_empty_label.setStyleSheet("color:#9a9a9a; padding: 4px 2px;")

        # ----- Three independent sections -----
        self.active_signal_section = CollapsibleSection(
            "Active Signal Devices",
            self.active_signal_tree,
            expanded=True,
        )
        self.active_mechanical_section = CollapsibleSection(
            "Active Mechanical Devices",
            self.active_mechanical_tree,
            expanded=False,
        )
        self.inactive_section = CollapsibleSection(
            "Inactive Devices",
            self.inactive_tree,
            expanded=False,
        )

        for section in (
            self.active_signal_section,
            self.active_mechanical_section,
            self.inactive_section,
        ):
            section.expandedChanged.connect(
                lambda _checked, s=section: self._on_section_toggled(s)
            )
            section.preferredHeightChanged.connect(self._schedule_section_reflow)

        self.active_signal_tree.preferredHeightChanged.connect(
            self._schedule_section_reflow
        )
        self.active_mechanical_tree.preferredHeightChanged.connect(
            self._schedule_section_reflow
        )
        self.inactive_tree.preferredHeightChanged.connect(self._schedule_section_reflow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(controls, 0)
        layout.addWidget(self.search_results, 0)
        layout.addWidget(self.search_empty_label, 0)

        self.sections_container = QWidget()
        self.sections_layout = QVBoxLayout(self.sections_container)
        self.sections_layout.setContentsMargins(0, 0, 0, 0)
        self.sections_layout.setSpacing(8)

        self.sections_layout.addWidget(self.active_signal_section, 0)
        self.sections_layout.addStretch(1)
        self.sections_layout.addWidget(self.active_mechanical_section, 0)
        self.sections_layout.addWidget(self.inactive_section, 0)

        layout.addWidget(self.sections_container, 1)

        self.active_signal_section.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Maximum
        )
        self.active_mechanical_section.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Maximum
        )
        self.inactive_section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        QTimer.singleShot(0, self._reflow_section_heights)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_section_reflow()

    def _on_section_toggled(self, section):
        self._last_toggled_section = section
        self._schedule_section_reflow()

    def _schedule_section_reflow(self):
        if self._reflow_pending:
            return
        self._reflow_pending = True
        QTimer.singleShot(0, self._reflow_section_heights)

    def _reflow_section_heights(self):
        self._reflow_pending = False

        sections = [
            self.active_signal_section,
            self.active_mechanical_section,
            self.inactive_section,
        ]

        container_h = self.sections_container.contentsRect().height()
        if container_h <= 0:
            return

        spacing = self.sections_layout.spacing()
        # items = top section + stretch + middle + bottom  => 4 items => 3 spacings
        available = max(0, container_h - spacing * 3)

        expanded_sections = [s for s in sections if s.is_expanded()]
        header_total = sum(s.header_height() for s in sections)
        padding_total = sum(s.content_vertical_padding() for s in expanded_sections)

        available_for_content = max(0, available - header_total - padding_total)

        preferred = {s: max(0, s.preferred_content_height()) for s in expanded_sections}
        preferred_total = sum(preferred.values())

        # enough room: everything natural, no internal scroll
        if preferred_total <= available_for_content:
            for s in sections:
                s.set_content_height_limit(None)
            return

        if not expanded_sections:
            return

        # start with preferred heights
        assigned = dict(preferred)

        # reduce overflow, first try the section that was most recently toggled
        overflow = preferred_total - available_for_content
        soft_min = 72
        hard_min = 36

        order = []
        if self._last_toggled_section in expanded_sections:
            order.append(self._last_toggled_section)

        others = [s for s in expanded_sections if s not in order]
        others.sort(key=lambda sec: preferred[sec], reverse=True)
        order.extend(others)

        # first pass: don't shrink below soft_min
        for s in order:
            if overflow <= 0:
                break
            reducible = max(0, assigned[s] - soft_min)
            take = min(reducible, overflow)
            assigned[s] -= take
            overflow -= take

        # second pass: if still overflow, allow smaller, but not too tiny
        for s in order:
            if overflow <= 0:
                break
            reducible = max(0, assigned[s] - hard_min)
            take = min(reducible, overflow)
            assigned[s] -= take
            overflow -= take

        # if panel is extremely tiny, distribute what's left evenly
        if overflow > 0:
            share = max(
                hard_min, available_for_content // max(1, len(expanded_sections))
            )
            for s in expanded_sections:
                assigned[s] = share

        for s in sections:
            if s.is_expanded():
                s.set_content_height_limit(assigned.get(s))
            else:
                s.set_content_height_limit(None)

    def add_device(self, meta: dict):
        self._all_meta_by_id[meta["id"]] = meta
        self.rebuild_views()
        self._update_search_results()

    def rebuild_views(self):
        active_signal = []
        active_mechanical = []
        inactive = []

        for meta in self._all_meta_by_id.values():
            if not meta.get("isActive", False):
                inactive.append(meta)
            elif meta.get("hasElectricalIO", False):
                active_signal.append(meta)
            else:
                active_mechanical.append(meta)

        self.active_signal_tree.populate(active_signal, self._group_mode)
        self.active_mechanical_tree.populate(active_mechanical, self._group_mode)
        self.inactive_tree.populate(inactive, self._group_mode)
        self._schedule_section_reflow()

    def _on_group_mode_changed(self, text: str):
        self._group_mode = text
        self.rebuild_views()
        self._update_search_results()

    def _match_meta(self, meta: dict, query: str) -> bool:
        q = query.lower().strip()
        if not q:
            return False

        fields = [
            meta.get("id", ""),
            meta.get("name", ""),
            meta.get("deviceType", ""),
            meta.get("deviceGroup", ""),
            " ".join(meta.get("deviceSystems", [])),
        ]
        return any(q in str(field).lower() for field in fields)

    def _section_name_for_meta(self, meta: dict) -> str:
        if not meta.get("isActive", False):
            return "Inactive Devices"
        if meta.get("hasElectricalIO", False):
            return "Active Signal Devices"
        return "Active Mechanical Devices"

    def _update_search_results(self):
        query = self.search_input.text().strip()
        self.search_results.clear()

        if not query:
            self.search_results.hide()
            self.search_empty_label.hide()
            self._schedule_section_reflow()
            return

        matches = []
        for meta in self._all_meta_by_id.values():
            if self._match_meta(meta, query):
                matches.append(meta)

        matches.sort(
            key=lambda m: (
                self._section_name_for_meta(m),
                (m.get("name") or "").lower(),
            )
        )

        if not matches:
            self.search_results.hide()
            self.search_empty_label.show()
            self._schedule_section_reflow()
            return

        self.search_empty_label.hide()
        for meta in matches:
            section = self._section_name_for_meta(meta)
            systems = normalize_systems(meta.get("deviceSystems", []))
            system_text = (
                " + ".join(systems)
                if len(systems) > 1
                else (systems[0] if systems else "Unassigned")
            )
            item = QListWidgetItem(f"{meta['name']}   [{section} / {system_text}]")
            item.setData(Qt.UserRole, meta["id"])
            self.search_results.addItem(item)

        self.search_results.show()
        self._schedule_section_reflow()

    def _activate_first_search_result(self):
        if self.search_results.isHidden() or self.search_results.count() == 0:
            return
        item = self.search_results.item(0)
        if item is not None:
            self._jump_to_device(item.data(Qt.UserRole))

    def _on_search_result_clicked(self, item: QListWidgetItem):
        device_id = item.data(Qt.UserRole)
        if device_id:
            self._jump_to_device(device_id)

    def _jump_to_device(self, device_id: str):
        meta = self._all_meta_by_id.get(device_id)
        if meta is None:
            return

        if not meta.get("isActive", False):
            self.inactive_section.set_expanded(True)
            self.inactive_tree.jump_to_device(device_id)
            self._last_toggled_section = self.inactive_section
        elif meta.get("hasElectricalIO", False):
            self.active_signal_section.set_expanded(True)
            self.active_signal_tree.jump_to_device(device_id)
            self._last_toggled_section = self.active_signal_section
        else:
            self.active_mechanical_section.set_expanded(True)
            self.active_mechanical_tree.jump_to_device(device_id)
            self._last_toggled_section = self.active_mechanical_section

        self._schedule_section_reflow()

    def activate_device(self, device_id: str):
        self._jump_to_device(device_id)
        meta = self._all_meta_by_id.get(device_id)
        if meta and meta.get("isActive", False) and meta.get("hasElectricalIO", False):
            self.deviceActivated.emit(device_id)


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=8, v_spacing=8):
        super().__init__(parent)
        self._items = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            widget = item.widget()
            space_x = self._h_spacing
            space_y = self._v_spacing
            hint = item.sizeHint()
            next_x = x + hint.width() + space_x
            if line_height > 0 and next_x - space_x > effective.right() + 1:
                x = effective.x()
                y += line_height + space_y
                next_x = x + hint.width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))

            x = next_x
            line_height = max(line_height, hint.height())

        total_height = (y + line_height - rect.y()) + margins.bottom()
        return max(total_height, 0)


class GraphLegendChip(QFrame):
    toggled = pyqtSignal(str, bool)

    def __init__(self, device_id: str, label: str, color: str, enabled: bool = True, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self._label_text = label
        self._accent_color = color
        self._enabled_state = bool(enabled)

        self.setCursor(Qt.PointingHandCursor)
        self.setFrameShape(QFrame.NoFrame)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.dot_label = QLabel("●")
        self.text_label = QLabel(label)
        self.text_label.setWordWrap(False)
        layout.addWidget(self.dot_label, 0)
        layout.addWidget(self.text_label, 0)

        self.set_series_enabled(self._enabled_state)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.set_series_enabled(not self._enabled_state)
            self.toggled.emit(self.device_id, self._enabled_state)
            event.accept()
            return
        super().mousePressEvent(event)

    def set_series_enabled(self, enabled: bool):
        self._enabled_state = bool(enabled)
        if self._enabled_state:
            self.setStyleSheet(
                f"QFrame {{ background: #1a1d1f; border: 1px solid #3b3f42; border-radius: 10px; }} "
                f"QLabel {{ color: #d9d9d9; border: none; background: transparent; }}"
            )
            self.dot_label.setStyleSheet(
                f"color: {self._accent_color}; border: none; background: transparent;"
            )
            self.text_label.setStyleSheet("color: #d9d9d9; border: none; background: transparent;")
        else:
            self.setStyleSheet(
                "QFrame { background: #141618; border: 1px solid #2d3134; border-radius: 10px; } "
                "QLabel { color: #6f7478; border: none; background: transparent; }"
            )
            self.dot_label.setStyleSheet("color: #6f7478; border: none; background: transparent;")
            self.text_label.setStyleSheet("color: #6f7478; border: none; background: transparent;")


class GraphWidgetSettingsPanel(QFrame):
    saveRequested = pyqtSignal(list, int)
    cancelRequested = pyqtSignal()

    def __init__(self, name_resolver, parent=None):
        super().__init__(parent)
        self._name_resolver = name_resolver
        self._device_ids = []
        self._duration_s = 60

        self.setObjectName("InlineGraphSettingsPanel")
        self.setFrameShape(QFrame.NoFrame)
        self.setVisible(False)
        self.setStyleSheet(
            """
            QFrame#InlineGraphSettingsPanel {
                background: #101214;
                border: 1px solid #31363b;
                border-radius: 10px;
            }
            QLabel {
                color: #f0f0f0;
                background: transparent;
                border: none;
            }
            QPushButton {
                color: #e8e8e8;
                background: #202428;
                border: 1px solid #454b50;
                border-radius: 8px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background: #2a2f34;
            }
            QSpinBox {
                background: #202428;
                color: #f0f0f0;
                border: 1px solid #454b50;
                border-radius: 8px;
                padding: 4px 6px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        intro = QLabel(
            "Current inputs are listed below. Add new ones by dragging from the library."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #aab2bd;")
        layout.addWidget(intro)

        inputs_title = QLabel("Inputs")
        inputs_title.setStyleSheet("font-weight: 700;")
        layout.addWidget(inputs_title)

        self.inputs_container = QWidget()
        self.inputs_layout = QVBoxLayout(self.inputs_container)
        self.inputs_layout.setContentsMargins(0, 0, 0, 0)
        self.inputs_layout.setSpacing(8)
        layout.addWidget(self.inputs_container)

        duration_row = QHBoxLayout()
        duration_row.setContentsMargins(0, 0, 0, 0)
        duration_row.setSpacing(10)
        duration_row.addWidget(QLabel("Duration time:"), 0)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 3600)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setFixedWidth(120)
        duration_row.addWidget(self.duration_spin, 0)
        duration_row.addStretch(1)
        layout.addLayout(duration_row)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        button_row.addStretch(1)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancelRequested.emit)
        button_row.addWidget(self.cancel_button, 0)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self._emit_save)
        button_row.addWidget(self.save_button, 0)

        layout.addLayout(button_row)

    def set_state(self, state: GraphCardState):
        self._device_ids = list(state.device_ids)
        self._duration_s = max(1, int(state.duration_s))
        self.duration_spin.setValue(self._duration_s)
        self._refresh_inputs()

    def _device_name(self, device_id: str) -> str:
        try:
            return self._name_resolver(device_id)
        except Exception:
            return device_id

    def _refresh_inputs(self):
        while self.inputs_layout.count():
            item = self.inputs_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self._device_ids:
            empty = QLabel(
                "All inputs have been removed. Click Save to delete this widget."
            )
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #aab2bd;")
            self.inputs_layout.addWidget(empty)
            return

        for device_id in list(self._device_ids):
            row = QFrame()
            row.setFrameShape(QFrame.NoFrame)
            row.setStyleSheet(
                "QFrame { background: #1a1d1f; border: 1px solid #31363b; border-radius: 8px; }"
            )
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 6, 10, 6)
            row_layout.setSpacing(8)

            label = QLabel(self._device_name(device_id))
            row_layout.addWidget(label, 1)

            remove_button = QPushButton("Delete")
            remove_button.setFixedWidth(78)
            remove_button.clicked.connect(lambda _=False, d=device_id: self._remove_device(d))
            row_layout.addWidget(remove_button, 0)

            self.inputs_layout.addWidget(row)

        self.inputs_layout.addStretch(1)

    def _remove_device(self, device_id: str):
        try:
            self._device_ids.remove(device_id)
        except ValueError:
            pass
        self._refresh_inputs()

    def _emit_save(self):
        self.saveRequested.emit(list(self._device_ids), max(1, int(self.duration_spin.value())))


class GraphWidgetCard(QFrame):
    dropDeviceRequested = pyqtSignal(str, object)
    settingsSaved = pyqtSignal(object, list, int)
    moveUpRequested = pyqtSignal(object)
    moveDownRequested = pyqtSignal(object)

    def __init__(self, state: GraphCardState, graph_widget: QWidget | None = None, name_resolver=None, parent=None):
        super().__init__(parent)
        self.state = state
        self.graph_widget = None
        self._name_resolver = name_resolver or (lambda value: value)

        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(
            """
            QFrame {
                background: #15181a;
                border: 1px solid #3a3f44;
                border-radius: 12px;
            }
            QLabel {
                color: #f0f0f0;
                background: transparent;
                border: none;
            }
            QPushButton {
                color: #e8e8e8;
                background: #202428;
                border: 1px solid #454b50;
                border-radius: 8px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background: #2a2f34;
            }
        """
        )

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(10)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        self.title_container = QWidget()
        self.title_container.setStyleSheet("background: transparent; border: none;")
        self.title_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title_block = QVBoxLayout(self.title_container)
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(2)

        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        self.title_label.setFont(title_font)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.summary_label.setStyleSheet("color: #aab2bd; border: none; background: transparent;")

        title_block.addWidget(self.title_label)
        title_block.addWidget(self.summary_label)

        header_layout.addWidget(self.title_container, 1)

        self.move_up_button = QPushButton("↑")
        self.move_up_button.setFixedSize(34, 30)
        self.move_up_button.setToolTip("Move widget up")
        self.move_up_button.clicked.connect(lambda: self.moveUpRequested.emit(self))
        header_layout.addWidget(self.move_up_button, 0, Qt.AlignTop)

        self.move_down_button = QPushButton("↓")
        self.move_down_button.setFixedSize(34, 30)
        self.move_down_button.setToolTip("Move widget down")
        self.move_down_button.clicked.connect(lambda: self.moveDownRequested.emit(self))
        header_layout.addWidget(self.move_down_button, 0, Qt.AlignTop)

        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedSize(34, 30)
        self.settings_button.setToolTip("Show graph widget settings")
        self.settings_button.clicked.connect(self.toggle_settings_panel)
        header_layout.addWidget(self.settings_button, 0, Qt.AlignTop)

        self.main_layout.addLayout(header_layout)

        self.settings_panel = GraphWidgetSettingsPanel(self._device_name, parent=self)
        self.settings_panel.saveRequested.connect(self._on_settings_saved)
        self.settings_panel.cancelRequested.connect(self.close_settings_panel)
        self.main_layout.addWidget(self.settings_panel, 1)

        self.graph_host = QFrame()
        self.graph_host.setFrameShape(QFrame.NoFrame)
        self.graph_host.setStyleSheet(
            "QFrame { background: #101214; border: 1px solid #2c3136; border-radius: 10px; }"
        )
        self.graph_layout = QVBoxLayout(self.graph_host)
        self.graph_layout.setContentsMargins(8, 8, 8, 8)
        self.graph_layout.setSpacing(0)
        self.main_layout.addWidget(self.graph_host, 1)

        self.legend_row = QWidget()
        self.legend_layout = FlowLayout(self.legend_row, margin=0, h_spacing=8, v_spacing=8)
        self.legend_row.setLayout(self.legend_layout)
        self.main_layout.addWidget(self.legend_row, 0)

        self._set_graph_widget(graph_widget)
        self.sync_from_state()
        self.sync_legend([])
        self._set_settings_mode(False)

    def _set_graph_widget(self, graph_widget: QWidget | None):
        while self.graph_layout.count():
            item = self.graph_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)

        self.graph_widget = graph_widget
        if graph_widget is None:
            placeholder = QLabel("Graph area will appear here when channels are added.")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color: #8f98a3; border: none; background: transparent;")
            self.graph_layout.addWidget(placeholder)
        else:
            self.graph_layout.addWidget(graph_widget)

    def sync_from_state(self):
        self.title_label.setText(self.state.title or "Signal Graph")
        count = len(self.state.device_ids)
        input_word = "input" if count == 1 else "inputs"
        self.summary_label.setText(f"{count} {input_word} · Duration: {int(self.state.duration_s)}s")
        self.title_label.updateGeometry()
        self.summary_label.updateGeometry()

    def set_reorder_enabled(self, can_move_up: bool, can_move_down: bool):
        self.move_up_button.setEnabled(bool(can_move_up))
        self.move_down_button.setEnabled(bool(can_move_down))

    def sync_legend(self, entries):
        while self.legend_layout.count():
            item = self.legend_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.deleteLater()

        if not entries:
            label = QLabel("Legend will appear here when channels are graphed.")
            label.setWordWrap(True)
            label.setStyleSheet("color: #8f98a3; border: none; background: transparent;")
            self.legend_layout.addWidget(label)
            return

        for entry in entries:
            if isinstance(entry, dict):
                device_id = entry.get("device_id", "")
                name = entry.get("label", device_id or "Unknown")
                color = entry.get("color", "#d0d0d0")
                enabled = bool(entry.get("enabled", True))
            else:
                if len(entry) >= 4:
                    device_id, name, color, enabled = entry[0], entry[1], entry[2], bool(entry[3])
                elif len(entry) >= 3:
                    device_id, name, color = entry[0], entry[1], entry[2]
                    enabled = True
                else:
                    device_id = name = entry[0]
                    color = entry[1] if len(entry) > 1 else "#d0d0d0"
                    enabled = True

            chip = GraphLegendChip(device_id, name, color, enabled=enabled)
            chip.toggled.connect(self._on_legend_toggled)
            self.legend_layout.addWidget(chip)

        self.legend_row.updateGeometry()

    def _on_legend_toggled(self, device_id: str, enabled: bool):
        if self.graph_widget is None:
            return
        toggle = getattr(self.graph_widget, "enableChannel", None)
        if callable(toggle):
            try:
                toggle(device_id, enabled)
            except Exception:
                log.exception("Failed to toggle graph series %s", device_id)

    def _device_name(self, device_id: str) -> str:
        try:
            return self._name_resolver(device_id)
        except Exception:
            return device_id

    def _set_settings_mode(self, enabled: bool):
        self.settings_panel.setVisible(enabled)
        self.graph_host.setVisible(not enabled)
        self.legend_row.setVisible(not enabled)
        self.settings_button.setToolTip("Hide graph widget settings" if enabled else "Show graph widget settings")
        self.settings_button.setText("✕" if enabled else "⚙")

    def toggle_settings_panel(self):
        if self.settings_panel.isVisible():
            self.close_settings_panel()
            return
        self.settings_panel.set_state(self.state)
        self._set_settings_mode(True)

    def close_settings_panel(self):
        self._set_settings_mode(False)

    def _on_settings_saved(self, device_ids: list[str], duration_s: int):
        self.close_settings_panel()
        self.settingsSaved.emit(self, list(device_ids), int(duration_s))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.title_label.updateGeometry()
        self.summary_label.updateGeometry()
        self.legend_row.updateGeometry()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(DEVICE_MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(DEVICE_MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(DEVICE_MIME_TYPE):
            event.ignore()
            return

        raw = bytes(event.mimeData().data(DEVICE_MIME_TYPE)).decode("utf-8").strip()
        if raw:
            self.dropDeviceRequested.emit(raw, self)
            event.acceptProposedAction()
        else:
            event.ignore()


class GraphWorkspace(QWidget):
    deviceDropped = pyqtSignal(str, object)

    def __init__(self, graph_widget: QWidget, graph_provider=None, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        self._primary_graph_widget = graph_widget
        self._graph_provider = graph_provider
        self._primary_graph_claimed = False
        self._device_names: dict[str, str] = {}
        self._cards: list[GraphWidgetCard] = []
        self.placeholder = QLabel(
            "Drag active signal devices here\n\n"
            "Drop on empty workspace to create a new graph widget, or drop on a card to add another input."
        )
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet(
            """
            QLabel {
                color: #9a9a9a;
                border: 2px dashed #444;
                border-radius: 12px;
                padding: 28px;
                background: #181818;
            }
        """
        )

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(12)
        self.scroll_layout.addStretch(1)
        self.scroll_area.setWidget(self.scroll_content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.placeholder)
        layout.addWidget(self.scroll_area, 1)

        self._refresh_empty_state()

    def _refresh_empty_state(self):
        has_cards = bool(self._cards)
        self.placeholder.setVisible(not has_cards)
        self.scroll_area.setVisible(has_cards)

    def _insert_card(self, card: GraphWidgetCard):
        self.scroll_layout.insertWidget(max(0, self.scroll_layout.count() - 1), card)

    def _default_duration(self) -> int:
        if self._cards:
            first_graph = getattr(self._cards[0], "graph_widget", None)
            try:
                return int(getattr(first_graph, "duration", 60))
            except Exception:
                return 60

        try:
            return int(getattr(self._primary_graph_widget, "duration", 60))
        except Exception:
            return 60

    def _title_for_ids(self, device_ids: list[str]) -> str:
        if not device_ids:
            return "Signal Graph"
        labels = [self._device_names.get(device_id, device_id) for device_id in device_ids]
        return ", ".join(labels)

    def _legend_entries_for(self, graph_widget: QWidget | None):
        if graph_widget is None:
            return []

        legend_entries = getattr(graph_widget, "legend_entries", None)
        if callable(legend_entries):
            try:
                return list(legend_entries())
            except Exception:
                log.exception("Failed to read graph legend entries from GraphView")

        entries = []
        sensors = getattr(graph_widget, "sensors", [])
        lines = getattr(graph_widget, "lines", [])
        is_enabled = getattr(graph_widget, "is_channel_enabled", None)

        for sensor, line in zip(sensors, lines):
            device_id = getattr(sensor, "device_id", "")
            label = getattr(sensor, "display_name", device_id or "Unknown")
            color = line.get_color() if hasattr(line, "get_color") else "#d0d0d0"
            enabled = True
            if callable(is_enabled) and device_id:
                try:
                    enabled = bool(is_enabled(device_id))
                except Exception:
                    enabled = True
            entries.append((device_id, label, color, enabled))

        return entries

    def _wire_card_graph_signals(self, card: GraphWidgetCard):
        graph_widget = card.graph_widget
        if graph_widget is None:
            return

        duration_changed = getattr(graph_widget, "durationChanged", None)
        if duration_changed is not None:
            duration_changed.connect(lambda value, c=card: self._on_card_duration_changed(c, value))

        series_changed = getattr(graph_widget, "seriesChanged", None)
        if series_changed is not None:
            series_changed.connect(lambda c=card: self._sync_card(c))

    def _new_graph_widget(self) -> QWidget:
        if not self._primary_graph_claimed:
            self._primary_graph_claimed = True
            return self._primary_graph_widget
        widget = GraphView()
        attach_provider = getattr(widget, "attach_graph_provider", None)
        if callable(attach_provider) and self._graph_provider is not None:
            attach_provider(self._graph_provider)
        return widget

    def _create_card(self) -> GraphWidgetCard:
        graph_widget = self._new_graph_widget()
        state = GraphCardState(
            title="Signal Graph",
            device_ids=[],
            duration_s=self._default_duration(),
        )

        set_duration = getattr(graph_widget, "set_duration", None)
        if callable(set_duration):
            try:
                set_duration(int(state.duration_s))
            except Exception:
                log.exception("Failed to apply initial duration to graph widget")

        card = GraphWidgetCard(state, graph_widget=graph_widget, name_resolver=self._device_name)
        card.dropDeviceRequested.connect(self.deviceDropped.emit)
        card.settingsSaved.connect(self._apply_card_settings)
        card.moveUpRequested.connect(self.move_card_up)
        card.moveDownRequested.connect(self.move_card_down)
        self._wire_card_graph_signals(card)
        self._cards.append(card)
        self._insert_card(card)
        self._sync_card(card)
        self._refresh_empty_state()
        self._update_reorder_controls()
        self._update_reorder_controls()
        return card

    def _sync_card(self, card: GraphWidgetCard):
        if card not in self._cards:
            return

        card.state.title = self._title_for_ids(list(card.state.device_ids))
        try:
            card.state.duration_s = int(getattr(card.graph_widget, "duration", card.state.duration_s))
        except Exception:
            pass
        card.sync_from_state()
        card.sync_legend(self._legend_entries_for(card.graph_widget))
        if getattr(card, "settings_panel", None) is not None and card.settings_panel.isVisible():
            card.settings_panel.set_state(card.state)

    def _on_card_duration_changed(self, card: GraphWidgetCard, value: int):
        if card not in self._cards:
            return
        card.state.duration_s = int(value)
        card.sync_from_state()

    def _device_name(self, device_id: str) -> str:
        return self._device_names.get(device_id, device_id)

    def _update_reorder_controls(self):
        total = len(self._cards)
        for index, card in enumerate(self._cards):
            card.set_reorder_enabled(index > 0, index < total - 1)

    def move_card_up(self, card: GraphWidgetCard):
        if card not in self._cards:
            return
        index = self._cards.index(card)
        if index <= 0:
            self._update_reorder_controls()
            return
        self._cards[index - 1], self._cards[index] = self._cards[index], self._cards[index - 1]
        insert_at = max(0, self.scroll_layout.count() - 1)
        self.scroll_layout.removeWidget(card)
        self.scroll_layout.insertWidget(index - 1, card)
        self._update_reorder_controls()

    def move_card_down(self, card: GraphWidgetCard):
        if card not in self._cards:
            return
        index = self._cards.index(card)
        if index >= len(self._cards) - 1:
            self._update_reorder_controls()
            return
        self._cards[index], self._cards[index + 1] = self._cards[index + 1], self._cards[index]
        self.scroll_layout.removeWidget(card)
        self.scroll_layout.insertWidget(index + 1, card)
        self._update_reorder_controls()

    def _remove_card(self, card: GraphWidgetCard):
        if card not in self._cards:
            return

        self._cards.remove(card)
        graph_widget = card.graph_widget

        if graph_widget is self._primary_graph_widget:
            clear_devices = getattr(graph_widget, "clear_devices", None)
            if callable(clear_devices):
                try:
                    clear_devices()
                except Exception:
                    log.exception("Failed to clear primary graph widget during card removal")
            try:
                graph_widget.setParent(None)
            except Exception:
                pass
            self._primary_graph_claimed = False

        card.setParent(None)
        card.deleteLater()
        self._refresh_empty_state()
        self._update_reorder_controls()

    def _apply_card_settings(self, card: GraphWidgetCard, device_ids: list[str], duration_s: int):
        if card not in self._cards:
            return

        duration_s = max(1, int(duration_s))
        graph_widget = card.graph_widget

        if graph_widget is not None:
            set_duration = getattr(graph_widget, "set_duration", None)
            if not callable(set_duration):
                set_duration = getattr(graph_widget, "setDuration", None)
            if callable(set_duration):
                try:
                    set_duration(duration_s)
                except Exception:
                    log.exception("Failed to update graph duration from settings")

        current_ids = list(card.state.device_ids)
        removed_ids = [device_id for device_id in current_ids if device_id not in device_ids]

        if graph_widget is not None and removed_ids:
            remove_device = getattr(graph_widget, "remove_device", None)
            if callable(remove_device):
                for device_id in removed_ids:
                    try:
                        remove_device(device_id)
                    except Exception:
                        log.exception("Failed to remove device %s from graph widget", device_id)

        card.state.device_ids = list(device_ids)
        card.state.duration_s = duration_s

        if not card.state.device_ids:
            self._remove_card(card)
            return

        self._sync_card(card)
        self._refresh_empty_state()
        self._update_reorder_controls()

    def add_graph_device(self, device, target_card: GraphWidgetCard | None = None):
        device_id = getattr(device, "device_id", None)
        if not device_id:
            return False

        if target_card is None or target_card not in self._cards:
            target_card = self._create_card()

        graph_widget = target_card.graph_widget
        if graph_widget is None:
            return False

        if device_id in target_card.state.device_ids:
            self._sync_card(target_card)
            return False

        self._device_names[device_id] = getattr(device, "display_name", device_id)

        add_device = getattr(graph_widget, "add_device", None)
        if not callable(add_device):
            add_device = getattr(graph_widget, "addSensor", None)
        if not callable(add_device):
            log.warning("Graph widget does not provide an add-device API")
            return False

        try:
            add_device(device, True)
        except Exception:
            log.exception("Failed to add device %s to graph widget", device_id)
            return False

        target_card.state.device_ids.append(device_id)
        self._sync_card(target_card)
        self._refresh_empty_state()
        return True

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(DEVICE_MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(DEVICE_MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(DEVICE_MIME_TYPE):
            event.ignore()
            return

        raw = bytes(event.mimeData().data(DEVICE_MIME_TYPE)).decode("utf-8").strip()
        if raw:
            self.deviceDropped.emit(raw, None)
            event.acceptProposedAction()
        else:
            event.ignore()


class EngineForceWidget(QWidget):
    """
    Four-sensor engine thrust visualizer.

    - Total thrust is shown in blue at the top-left.
      Total is shown only when ALL four sensors are present; otherwise it shows "-- N".
    - Four sensor readings are shown around the circle: Up / Right / Down / Left.
      Missing sensor values are shown as:
          --
          N
    - The dot shows whether thrust is centered:
        dx = (Right - Left) / Total
        dy = (Up - Down) / Total
      If any sensor is missing (or Total is ~0), the dot stays centered and is drawn gray.
    """

    def __init__(self, parent=None, dot_gain=0.92):
        super().__init__(parent)

        self.up_n = None
        self.right_n = None
        self.down_n = None
        self.left_n = None

        self.dot_gain = float(dot_gain)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(200)

    def set_sensors(self, up=None, right=None, down=None, left=None):
        self.up_n = None if up is None else float(up)
        self.right_n = None if right is None else float(right)
        self.down_n = None if down is None else float(down)
        self.left_n = None if left is None else float(left)
        self.update()

    @staticmethod
    def _clamp(v, lo, hi):
        return lo if v < lo else hi if v > hi else v

    def _sum_available(self):
        vals = [self.up_n, self.right_n, self.down_n, self.left_n]
        return sum(v for v in vals if v is not None)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        base = max(1.0, min(w, h))

        pad = self._clamp(base * 0.03, 6.0, 16.0)
        gap = self._clamp(base * 0.025, 6.0, 14.0)

        total_fs = int(self._clamp(base * 0.09, 14.0, 30.0))
        val_fs = int(self._clamp(base * 0.065, 10.0, 20.0))
        unit_fs = int(self._clamp(val_fs * 0.80, 8.0, 16.0))

        circle_pen_w = int(self._clamp(base * 0.012, 2.0, 5.0))
        dot_r = int(self._clamp(base * 0.022, 6.0, 12.0))
        center_r = int(self._clamp(base * 0.015, 4.0, 8.0))

        box_w = self._clamp(base * 0.18, 52.0, 92.0)
        box_h = self._clamp(base * 0.13, 34.0, 52.0)

        p.fillRect(0, 0, w, h, QColor(0, 0, 0, 0))

        all_present = (
            self.up_n is not None
            and self.right_n is not None
            and self.down_n is not None
            and self.left_n is not None
        )

        # --- Total (pinned top-left) ---
        total_font = QFont("Arial", total_fs, QFont.Bold)
        p.setFont(total_font)
        p.setPen(QColor("#66aaff"))

        total_rect_h = int(total_fs * 1.6)
        total_rect = QRect(int(pad), int(pad), int(w * 0.6), total_rect_h)

        if all_present:
            total = self._sum_available()
            total_text = f"{total:.1f} N"
        else:
            total = 0.0  # keep a numeric fallback for dot logic
            total_text = "-- N"

        p.drawText(total_rect, Qt.AlignLeft | Qt.AlignVCenter, total_text)

        top_area = int(pad + total_rect_h + pad * 0.4)

        # --- Compute circle radius ---
        max_radius_x = (w - 2.0 * (box_w + gap + pad)) / 2.0
        max_radius_y = (h - top_area - 2.0 * (box_h + gap) - pad) / 2.0
        radius = min(max_radius_x, max_radius_y)
        radius = max(40.0, radius)

        used_h = (box_h + gap) + (2.0 * radius) + (box_h + gap)
        avail_h = max(0.0, (h - top_area) - pad)
        y_offset = (avail_h - used_h) * 0.5
        if y_offset < 0:
            y_offset = 0.0

        cx = w * 0.5
        cy = top_area + y_offset + (box_h + gap) + radius

        # --- Draw circle ---
        p.setPen(QPen(QColor("#d0d0d0"), circle_pen_w))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(
            int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2)
        )

        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#bfbfbf"))
        p.drawEllipse(
            int(cx - center_r), int(cy - center_r), int(center_r * 2), int(center_r * 2)
        )

        # --- Draw sensor boxes (two-line: value / N) ---
        val_font = QFont("Arial", val_fs, QFont.Bold)
        unit_font = QFont("Arial", unit_fs, QFont.Bold)
        p.setPen(QColor("#e0e0e0"))

        def draw_value_box(x, y, v):
            rect = QRect(int(x), int(y), int(box_w), int(box_h))
            upper = QRect(rect.x(), rect.y(), rect.width(), rect.height() // 2)
            lower = QRect(
                rect.x(),
                rect.y() + rect.height() // 2,
                rect.width(),
                rect.height() - rect.height() // 2,
            )

            p.setFont(val_font)
            if v is None:
                p.drawText(upper, Qt.AlignCenter, "--")
            else:
                p.drawText(upper, Qt.AlignCenter, f"{v:.1f}")

            p.setFont(unit_font)
            p.drawText(lower, Qt.AlignCenter, "N")

        up_x = cx - box_w / 2.0
        up_y = cy - radius - gap - box_h

        down_x = cx - box_w / 2.0
        down_y = cy + radius + gap

        left_x = cx - radius - gap - box_w
        left_y = cy - box_h / 2.0

        right_x = cx + radius + gap
        right_y = cy - box_h / 2.0

        def nudge_into_view(x, y):
            nx = x
            ny = y
            if nx < pad:
                nx = pad
            if nx + box_w > w - pad:
                nx = w - pad - box_w
            if ny < top_area:
                ny = top_area
            if ny + box_h > h - pad:
                ny = h - pad - box_h
            return nx, ny

        up_x, up_y = nudge_into_view(up_x, up_y)
        right_x, right_y = nudge_into_view(right_x, right_y)
        down_x, down_y = nudge_into_view(down_x, down_y)
        left_x, left_y = nudge_into_view(left_x, left_y)

        draw_value_box(up_x, up_y, self.up_n)
        draw_value_box(right_x, right_y, self.right_n)
        draw_value_box(down_x, down_y, self.down_n)
        draw_value_box(left_x, left_y, self.left_n)

        # --- Dot (imbalance) ---
        eps = 1e-6
        if all_present and total > eps:
            dx = (self.right_n - self.left_n) / total
            dy = (self.up_n - self.down_n) / total
            dot_color = QColor("#d32f2f")
        else:
            dx = 0.0
            dy = 0.0
            dot_color = QColor("#888888")

        mag = math.hypot(dx, dy)
        if mag > 1.0:
            dx /= mag
            dy /= mag

        dot_x = cx + dx * radius * self.dot_gain
        dot_y = cy - dy * radius * self.dot_gain

        p.setBrush(dot_color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(
            int(dot_x - dot_r), int(dot_y - dot_r), int(dot_r * 2), int(dot_r * 2)
        )

        p.end()


# =========================================================
# Fuel Capacity widgets (Tanks)
# =========================================================
class TankGaugeWidget(QWidget):
    """
    Single tank gauge:
    - 4 lines of text on top (pressure/temp/level/valve)
    - tank rectangle with fill
    - label at bottom (IPA/LOX)
    - emits clicked(name) when pressed
    """

    clicked = pyqtSignal(str)

    def __init__(self, name: str, fill_color: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.fill_color = QColor(fill_color)

        self.pressure_psi = None
        self.temp_c = None
        self.level_pct = None
        self.valve_open_pct = None

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(220)
        self.setCursor(Qt.PointingHandCursor)

    def set_data(
        self, pressure_psi=None, temp_c=None, level_pct=None, valve_open_pct=None
    ):
        self.pressure_psi = None if pressure_psi is None else float(pressure_psi)
        self.temp_c = None if temp_c is None else float(temp_c)
        self.level_pct = None if level_pct is None else float(level_pct)
        self.valve_open_pct = None if valve_open_pct is None else float(valve_open_pct)
        self.update()

    @staticmethod
    def _clamp(v, lo, hi):
        return lo if v < lo else hi if v > hi else v

    @staticmethod
    def _fmt_num(v, digits0=True):
        if v is None:
            return "--"
        return f"{v:.0f}" if digits0 else f"{v:.1f}"

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.name)
        super().mousePressEvent(e)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        base = max(1.0, min(w, h))

        pad = self._clamp(base * 0.06, 8.0, 16.0)
        line_gap = self._clamp(base * 0.015, 2.0, 6.0)

        txt_fs = int(self._clamp(base * 0.085, 10.0, 15.0))
        label_fs = int(self._clamp(base * 0.10, 12.0, 18.0))

        txt_font = QFont("Arial", txt_fs, QFont.DemiBold)
        label_font = QFont("Arial", label_fs, QFont.Bold)

        p.fillRect(0, 0, w, h, QColor(0, 0, 0, 0))

        # ---- Top 4 lines ----
        p.setFont(txt_font)
        p.setPen(QColor("#e6e6e6"))

        # Missing data displays as: "-- <unit>"
        # Standard unit formatting: psi, °C, %

        lines = [
            f"Pres: {self._fmt_num(self.pressure_psi)} psi",
            f"Temp: {self._fmt_num(self.temp_c)} °C",
            f"Flow: {self._fmt_num(self.valve_open_pct)} %",
            f"Level: {self._fmt_num(self.level_pct)} %",
        ]

        fm = p.fontMetrics()
        line_h = fm.height()
        text_block_h = line_h * 4 + line_gap * 3

        y = pad
        for i, s in enumerate(lines):
            r = QRect(int(pad), int(y), int(w - 2 * pad), int(line_h))
            p.drawText(r, Qt.AlignHCenter | Qt.AlignVCenter, s)
            y += line_h + (line_gap if i < 3 else 0)

        # ---- Label area ----
        p.setFont(label_font)
        label_h = p.fontMetrics().height()

        # ---- Tank geometry ----
        tank_top = pad + text_block_h + pad * 0.35
        tank_bottom = h - pad - label_h - pad * 0.25
        tank_h = max(80.0, tank_bottom - tank_top)

        tank_w = min(w - 2 * pad, tank_h * 0.38)
        tank_w = max(42.0, tank_w)

        tank_x = (w - tank_w) * 0.5
        tank_y = tank_top

        # ---- Draw tank body ----
        border_w = int(self._clamp(base * 0.012, 2.0, 4.0))
        p.setPen(QPen(QColor("#cfcfcf"), border_w))
        p.setBrush(QColor("#f2f2f2"))
        p.drawRect(int(tank_x), int(tank_y), int(tank_w), int(tank_h))

        # ---- Fill ----
        inner_pad = border_w + 1
        inner = QRect(
            int(tank_x + inner_pad),
            int(tank_y + inner_pad),
            int(tank_w - 2 * inner_pad),
            int(tank_h - 2 * inner_pad),
        )

        lvl = self.level_pct
        if lvl is None:
            # No data -> treat fill as 0% internally
            lvl = 0.0
            fill_color = QColor("#444444")
        else:
            lvl = self._clamp(lvl, 0.0, 100.0)
            fill_color = self.fill_color

        fill_h = int(inner.height() * (lvl / 100.0))
        fill_rect = QRect(
            inner.x(), inner.y() + inner.height() - fill_h, inner.width(), fill_h
        )

        p.setPen(Qt.NoPen)
        p.setBrush(fill_color)
        p.drawRect(fill_rect)

        # ---- Bottom label ----
        p.setFont(label_font)
        p.setPen(QColor("#e6e6e6"))
        label_rect = QRect(
            int(pad), int(h - pad - label_h), int(w - 2 * pad), int(label_h)
        )
        p.drawText(label_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.name)

        p.end()


class TelemetryWidget(QWidget):
    """
    Two-tank telemetry panel (IPA + LOX) with an info label below.
    Clicking a tank updates info text and emits tank_clicked(name).
    """

    tank_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.ipa = TankGaugeWidget("IPA", "#ff1e1e")
        self.lox = TankGaugeWidget("LOX", "#3b22ff")

        self.info_label = QLabel("--")
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color:#cfcfcf; font-weight:600;")

        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(18)
        row_lay.addWidget(self.ipa, 1)
        row_lay.addWidget(self.lox, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(row, 1)
        lay.addWidget(self.info_label, 0)

        self.ipa.clicked.connect(self._on_tank_clicked)
        self.lox.clicked.connect(self._on_tank_clicked)

        # Default state: no data (shows "-- <unit>" and level fill defaults to 0%)
        self.set_ipa()
        self.set_lox()

    def _on_tank_clicked(self, name: str):
        self.info_label.setText(f"{name} tank selected.")
        self.tank_clicked.emit(name)

    def set_ipa(
        self, pressure_psi=None, temp_c=None, level_pct=None, valve_open_pct=None
    ):
        self.ipa.set_data(pressure_psi, temp_c, level_pct, valve_open_pct)

    def set_lox(
        self, pressure_psi=None, temp_c=None, level_pct=None, valve_open_pct=None
    ):
        self.lox.set_data(pressure_psi, temp_c, level_pct, valve_open_pct)

    def set_info(self, text: str):
        self.info_label.setText(text)



class ControllerWindow(QMainWindow):
    STATUS_STYLE = {
        "idle": ("Idle", "#616161", "#ffffff"),
        "normal": ("Normal", "#2e7d32", "#ffffff"),
        "hold": ("Hold", "#1565C0", "#ffffff"),
        "abort": ("Abort", "#EF6C00", "#ffffff"),
        "estop": ("E-Stop", "#C62828", "#ffffff"),
    }
    HEALTH_STYLE = {
        "default": ("--", "#616161", "#ffffff"),
        "ok": ("OK", "#2e7d32", "#ffffff"),
        "attention": ("Attention", "#F9A825", "#000000"),
        "alarm": ("Alarm", "#C62828", "#ffffff"),
    }
    MODE_STYLE = {
        "auto": ("Auto", "#EF6C00", "#ffffff"),
        "manual": ("Manual", "#EF6C00", "#ffffff"),
        "playback": ("Playback", "#1565C0", "#ffffff"),
    }
    SCRIPT_STYLE = {
        "idle": ("Idle", "#616161", "#ffffff"),
        "running": ("Running", "#EF6C00", "#ffffff"),
        "pause": ("Paused", "#1565C0", "#ffffff"),
    }
    AUX_CLOCK_STYLE = {
        "neutral": ("#f5f5f5", "transparent"),
        "recording": ("#4aa3ff", "transparent"),
        "playback": ("#4aa3ff", "transparent"),
        "warning": ("#ffca28", "transparent"),
    }

    def __init__(
        self,
        loghandler=None,
        autopoller=None,
        playback_mode=False,
        test_name=None,
        manager=None,
    ):
        super().__init__()
        self.manager = manager

        self._init_mode_state(autopoller, playback_mode, test_name)
        self._init_shared_runtime()
        self._init_mode_specific_runtime()
        self._build_shared_widgets(loghandler)
        self._build_mode_specific_widgets()
        self._build_main_layout()
        self._connect_shared_signals()
        self._connect_mode_specific_signals()
        self._set_initial_state()

    # ----- Initialization phases -----

    def _init_mode_state(self, autopoller, playback_mode, test_name):
        logging.getLogger("qdarkstyle").setLevel(logging.ERROR)
        self.log = logging.getLogger("controller_window")

        self.autopoller = autopoller
        self.playback_mode = playback_mode
        self.test_name = test_name

        self.devices: dict[str, object] = {}
        self.device_meta: dict[str, dict] = {}

        self.mission_start_time = None
        self.mission_running = False

        self._backend_mission_clock = None
        self._backend_recording_clock = None
        self._backend_playback_clock = None
        self._recording_started_dt: datetime | None = None

        self._playback_state_manager = None  # set by window_host after construction
        self._playback_time_fallback = 0.0
        self.playback_duration_seconds = None
        self._playback_running = False       # legacy fallback; manager is authority when set
        self._playback_speed = 1.0           # legacy fallback
        self._playback_speed_steps = (0.25, 0.5, 1.0, 2.0, 4.0)
        self._playback_anchor = 0.0          # legacy fallback
        self._playback_mono_start = 0.0      # legacy fallback

    @property
    def playback_time(self) -> float:
        psm = getattr(self, '_playback_state_manager', None)
        if psm is not None:
            return psm.position_seconds
        return getattr(self, '_playback_time_fallback', 0.0)

    @playback_time.setter
    def playback_time(self, value: float) -> None:
        value = max(0.0, float(value))
        psm = getattr(self, '_playback_state_manager', None)
        if psm is not None:
            psm.set_position(value)
        self._playback_time_fallback = value

    def _init_shared_runtime(self):
        self.setWindowTitle("minTS Controller - Left Screen")
        QApplication.setStyle("Fusion")
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt5"))
        self.setFont(QFont("Arial", 10))

    def _init_mode_specific_runtime(self):
        if self.playback_mode:
            self.graph_provider = PlaybackGraphDataProvider()
            self.live_telemetry_poller = None
        else:
            self.graph_provider = LiveGraphDataProvider()
            self.live_telemetry_poller = LiveTelemetryPoller(self.autopoller)

    def _build_shared_widgets(self, loghandler):
        self.timeline = TimelineView(
            playback_mode=self.playback_mode,
            show_event_columns=False,
            embedded=True,
        )

        self.graph = GraphView()
        attach_provider = getattr(self.graph, "attach_graph_provider", None)
        if callable(attach_provider) and self.graph_provider is not None:
            attach_provider(self.graph_provider)
            self.graph_provider.start()

        self.console = ConsoleView(loghandler, playback_mode=self.playback_mode)
        self.exporter = ExportView()
        self.device_library = DeviceLibraryPanel()
        self.workspace = GraphWorkspace(self.graph, graph_provider=self.graph_provider)

        self.engine_force_widget = EngineForceWidget(dot_gain=0.90)
        self.engine_force_widget.set_sensors(None, None, None, None)

        self.telemetry_widget = TelemetryWidget()

    def _build_mode_specific_widgets(self):
        if self.playback_mode:
            self._build_playback_widgets()
        else:
            self._build_live_widgets()

    def _build_live_widgets(self):
        if self.live_telemetry_poller is not None:
            try:
                self.live_telemetry_poller.start()
            except Exception:
                self.log.exception("Failed to start live telemetry poller")

        self.scripter = ScriptView(
            MintsScriptAPI(
                devices=self.devices,
                abort=self.abort,
            )
        )

    def _build_playback_widgets(self):
        pass

    def _build_main_layout(self):
        central = QWidget()
        self.setCentralWidget(central)
        central.setStyleSheet("background:#121212;")

        self.mainlayout = QVBoxLayout(central)
        self.mainlayout.setSpacing(0)
        self.mainlayout.setContentsMargins(0, 0, 0, 0)

        self.mainlayout.addWidget(self._create_header_bar())
        self.mainlayout.addWidget(self._create_timeline_bar())

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body_layout = QHBoxLayout(body)
        body_layout.setSpacing(0)
        body_layout.setContentsMargins(8, 8, 8, 8)

        body_split = QSplitter(Qt.Horizontal)
        body_split.setHandleWidth(4)
        body_split.setChildrenCollapsible(False)
        body_split.setOpaqueResize(True)

        body_split.setStyleSheet(
            """
            QSplitter::handle {
                background: #3a3a3a;
            }
            QSplitter::handle:hover {
                background: #5a5a5a;
            }
        """
        )

        left_area = self._create_left_main_area()
        right_area = self._create_right_controller_area()

        body_split.addWidget(left_area)
        body_split.addWidget(right_area)

        body_split.setStretchFactor(0, 3)
        body_split.setStretchFactor(1, 2)
        body_split.setSizes([1200, 800])

        body_layout.addWidget(body_split, 1)
        self.mainlayout.addWidget(body, 1)

    def _connect_shared_signals(self):
        self.timeline.stage_changed.connect(self.set_stages)
        self.workspace.deviceDropped.connect(self._on_device_requested)
        self.device_library.deviceActivated.connect(self._on_device_requested)
        self.telemetry_widget.tank_clicked.connect(self._on_tank_clicked)

        self.display_timer = QTimer(self)
        self.display_timer.timeout.connect(self._update_time_displays)
        self.display_timer.start(100)

        self._playback_advance_timer = QTimer(self)
        self._playback_advance_timer.setInterval(100)
        self._playback_advance_timer.timeout.connect(self._on_playback_advance)

    def _connect_mode_specific_signals(self):
        if self.playback_mode:
            self.timeline.seek_requested.connect(self._on_timeline_seek)

            from PyQt5.QtGui import QKeySequence
            sc = QShortcut(QKeySequence("P"), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(self._on_playback_shortcut)
            self._playback_shortcut = sc  # prevent GC

            slower = QShortcut(QKeySequence("["), self)
            slower.setContext(Qt.WindowShortcut)
            slower.activated.connect(lambda: self._step_playback_speed(-1))
            self._playback_slower_shortcut = slower

            faster = QShortcut(QKeySequence("]"), self)
            faster.setContext(Qt.WindowShortcut)
            faster.activated.connect(lambda: self._step_playback_speed(1))
            self._playback_faster_shortcut = faster

    def _set_initial_state(self):
        self.set_status("idle" if not self.playback_mode else "hold")
        self.set_health("default" if not self.playback_mode else "ok")
        self.set_mode("playback" if self.playback_mode else "auto")
        self.set_script_state("idle" if not self.playback_mode else "pause")
        self.set_stages("Prev", "Current", "Next")

    def closeEvent(self, event):
        if not self.playback_mode and not getattr(self, "_finalization_bypass", False):
            snapshot = getattr(self, "_last_backend_snapshot", None)
            run = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
            consumed = run.get("recording_session_consumed", False)
            archive_complete = run.get("archive_complete", False)
            is_running = run.get("is_running", False)

            if consumed and not archive_complete and not is_running:
                from gui.finalization_guard import (
                    FinalizationWaitDialog,
                    RESULT_COMPLETED,
                    RESULT_FORCE_CLOSE,
                    start_finalization_auto_close_timer,
                )

                def _check() -> bool:
                    s = getattr(self, "_last_backend_snapshot", None)
                    r = s.get("run", {}) if isinstance(s, dict) else {}
                    return bool(r.get("archive_complete"))

                dialog = FinalizationWaitDialog(self, _check)
                dialog.exec_()

                if dialog.result_code not in (RESULT_COMPLETED, RESULT_FORCE_CLOSE):
                    start_finalization_auto_close_timer(self, _check)
                    event.ignore()
                    return

        poller = getattr(self, "live_telemetry_poller", None)
        if poller is not None:
            poller.close()

        provider = getattr(self, "graph_provider", None)
        if provider is not None:
            try:
                provider.stop()
            except Exception:
                self.log.exception("Failed to stop graph provider during close")

        if self.manager:
            self.manager.close_all()
        event.accept()

    # =========================================================
    # Header Bar
    # =========================================================
    def _create_header_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("headerBar")
        bar.setStyleSheet(
            """
            QFrame#headerBar{
                background:#151515;
                border:0px;
            }
            QFrame#headerBar QWidget{
                background: transparent;
                border: 0px;
            }
            QFrame#headerBar QLabel{
                background: transparent;
                border: none;
                color: #eaeaea;
            }
        """
        )

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)

        title = QLabel("minTS SCADA Controller")
        title.setFont(QFont("Arial", 20, QFont.Bold))
        title.setStyleSheet("color:#f5f5f5; background: transparent; border: none;")
        lay.addWidget(title, 0, Qt.AlignVCenter)

        stages = QWidget()
        slay = QHBoxLayout(stages)
        slay.setContentsMargins(0, 0, 0, 0)
        slay.setSpacing(6)

        self.stage_prev = self._make_stage_box("Prev")
        self.stage_curr = self._make_stage_box("Current")
        self.stage_next = self._make_stage_box("Next")

        slay.addWidget(self.stage_prev)
        slay.addWidget(self.stage_curr)
        slay.addWidget(self.stage_next)
        lay.addWidget(stages, 0, Qt.AlignVCenter)

        lay.addStretch(1)

        center_clock = QWidget()
        center_clock_lay = QVBoxLayout(center_clock)
        center_clock_lay.setContentsMargins(0, 0, 0, 0)
        center_clock_lay.setSpacing(0)

        self.mission_time_label = QLabel("T+00:00:00.000")
        self.mission_time_label.setFont(QFont("Courier New", 22, QFont.Bold))
        self.mission_time_label.setStyleSheet(
            "color:#21c45a; padding:0 12px; background: transparent; border:none;"
        )
        self.mission_time_label.setAlignment(Qt.AlignCenter)
        center_clock_lay.addWidget(self.mission_time_label, 0, Qt.AlignCenter)

        self.aux_time_label = QLabel("Total Duration: --" if self.playback_mode else "Not Recording")
        self.aux_time_label.setFont(QFont("Arial", 11, QFont.Bold))
        self.aux_time_label.setAlignment(Qt.AlignCenter)
        center_clock_lay.addWidget(self.aux_time_label, 0, Qt.AlignCenter)
        self._set_aux_clock_display(
            "Total Duration: --" if self.playback_mode else "Not Recording",
            accent="playback" if self.playback_mode else "neutral",
        )

        lay.addWidget(center_clock, 0, Qt.AlignVCenter)

        lay.addStretch(1)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(4)

        row1 = QWidget()
        row1_lay = QHBoxLayout(row1)
        row1_lay.setContentsMargins(0, 0, 0, 0)
        row1_lay.setSpacing(10)

        status_label = QLabel("Status:")
        status_label.setFont(QFont("Arial", 18, QFont.Bold))
        status_label.setStyleSheet(
            "color:#eaeaea; background: transparent; border:none;"
        )
        row1_lay.addWidget(status_label)

        self.status_badge = QLabel("Idle")
        self._set_badge(self.status_badge, "Idle", "#616161", "#ffffff", big=True)
        row1_lay.addWidget(self.status_badge)

        row1_lay.addSpacing(16)

        health_label = QLabel("Health:")
        health_label.setFont(QFont("Arial", 18, QFont.Bold))
        health_label.setStyleSheet(
            "color:#eaeaea; background: transparent; border:none;"
        )
        row1_lay.addWidget(health_label)

        self.health_badge = QLabel("--")
        self._set_badge(self.health_badge, "--", "#616161", "#ffffff", big=True)
        row1_lay.addWidget(self.health_badge)

        row1_lay.addStretch(1)
        rlay.addWidget(row1)

        row2 = QWidget()
        row2_lay = QHBoxLayout(row2)
        row2_lay.setContentsMargins(0, 0, 0, 0)
        row2_lay.setSpacing(8)

        mode_label = QLabel("Mode:")
        mode_label.setFont(QFont("Arial", 12, QFont.Bold))
        mode_label.setStyleSheet("color:#eaeaea; background: transparent; border:none;")
        row2_lay.addWidget(mode_label)

        self.mode_badge = QLabel("Auto")
        self._set_badge(self.mode_badge, "Auto", "#EF6C00", "#ffffff", big=False)
        row2_lay.addWidget(self.mode_badge)

        script_label = QLabel("Script:")
        script_label.setFont(QFont("Arial", 12, QFont.Bold))
        script_label.setStyleSheet(
            "color:#eaeaea; background: transparent; border:none;"
        )
        row2_lay.addWidget(script_label)

        self.script_badge = QLabel("Idle")
        self._set_badge(self.script_badge, "Idle", "#616161", "#ffffff", big=False)
        row2_lay.addWidget(self.script_badge)

        row2_lay.addStretch(1)

        self.clock_label = QLabel("00:00:00")
        self.clock_label.setFont(QFont("Courier New", 12))
        self.clock_label.setStyleSheet(
            "color:#cfcfcf; background: transparent; border:none;"
        )
        row2_lay.addWidget(self.clock_label)

        rlay.addWidget(row2)

        lay.addWidget(right, 0, Qt.AlignVCenter)
        return bar

    def _make_stage_box(self, title: str) -> QWidget:
        box = QFrame()
        box.setFixedSize(130, 48)
        box.setStyleSheet(
            """
            QFrame{
                background:#232323;
                border-radius:8px;
                border:1px solid #555;
            }
        """
        )
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(0)

        t = QLabel(title)
        t.setFont(QFont("Arial", 9, QFont.Bold))
        t.setStyleSheet("color:#bdbdbd; background: transparent; border: none;")
        v.addWidget(t)

        val = QLabel("(placeholder)")
        val.setFont(QFont("Arial", 10))
        val.setStyleSheet("color:#ffffff; background: transparent; border: none;")
        v.addWidget(val)

        box._value_label = val
        return box

    # =========================================================
    # Timeline Bar
    # =========================================================
    def _create_timeline_bar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("timelineBar")
        frame.setStyleSheet(
            """
            QFrame#timelineBar{
                background:#2a2d2f;
                border:0px;
            }
        """
        )

        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(0)

        self.timeline.setStyleSheet("background: transparent; border:none;")
        self.timeline.setMinimumHeight(56)
        self.timeline.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay.addWidget(self.timeline)
        return frame

    # =========================================================
    # Left area:
    # Devices | Main View (Graph + AutoPollerRow inside)
    # =========================================================
    def _create_left_main_area(self) -> QWidget:
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(3)
        split.setChildrenCollapsible(False)

        dev_panel = self._panel("Device Library", self.device_library)
        dev_panel.setMinimumWidth(320)
        split.addWidget(dev_panel)

        main_view = QWidget()
        mv = QVBoxLayout(main_view)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(8)

        mv.addWidget(self.workspace, 1)

        if (self.autopoller is not None) and (not self.playback_mode):
            mv.addLayout(AutoPollerRow(self.autopoller))

        workspace_panel = self._panel("Workspace", main_view)
        split.addWidget(workspace_panel)

        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([340, 1000])
        return split

    # =========================================================
    # Right column (mode-dispatched):
    #   Live:     Logs | Fuel + Script + Engine | button column
    #   Playback: Logs | Fuel + Engine (no Script, no buttons)
    # =========================================================
    def _create_right_controller_area(self) -> QWidget:
        if self.playback_mode:
            return self._create_playback_right_controller_area()
        return self._create_live_right_controller_area()

    def _create_live_right_content_stack(self) -> QSplitter:
        main_stack = QSplitter(Qt.Vertical)
        main_stack.setHandleWidth(2)
        main_stack.setChildrenCollapsible(False)

        # Top: Logs
        main_stack.addWidget(self._panel("Logs", self.console))

        # Bottom: Fuel Capacity + Script stack
        bottom_row = QSplitter(Qt.Horizontal)
        bottom_row.setHandleWidth(2)
        bottom_row.setChildrenCollapsible(False)

        # Fuel Capacity panel
        bottom_row.addWidget(self._panel("Fuel Capacity", self.telemetry_widget))

        # Script area: top is Script Control, bottom is Engine Force
        script_stack = QSplitter(Qt.Vertical)
        script_stack.setHandleWidth(2)
        script_stack.setChildrenCollapsible(False)

        script_stack.addWidget(self._panel("Script Control", self.scripter))
        script_stack.addWidget(self._panel("Engine Force", self.engine_force_widget))
        # Give the engine widget enough height by default
        script_stack.setSizes([240, 340])

        bottom_row.addWidget(script_stack)
        bottom_row.setStretchFactor(0, 1)
        bottom_row.setStretchFactor(1, 1)
        bottom_row.setSizes([520, 520])

        main_stack.addWidget(bottom_row)
        main_stack.setSizes([620, 380])

        return main_stack

    def _create_playback_right_content_stack(self) -> QSplitter:
        main_stack = QSplitter(Qt.Vertical)
        main_stack.setHandleWidth(2)
        main_stack.setChildrenCollapsible(False)

        main_stack.addWidget(self._panel("Logs", self.console))

        bottom_row = QSplitter(Qt.Horizontal)
        bottom_row.setHandleWidth(2)
        bottom_row.setChildrenCollapsible(False)

        bottom_row.addWidget(self._panel("Fuel Capacity", self.telemetry_widget))
        bottom_row.addWidget(self._panel("Engine Force", self.engine_force_widget))
        bottom_row.setStretchFactor(0, 1)
        bottom_row.setStretchFactor(1, 1)
        bottom_row.setSizes([520, 520])

        main_stack.addWidget(bottom_row)
        main_stack.setSizes([620, 380])

        return main_stack

    def _create_button_column(self) -> QFrame:
        btn_col = QFrame()
        btn_col.setFixedWidth(170)
        btn_col.setStyleSheet(
            "QFrame{background:#1e1e1e; border-radius:10px; border:1px solid #444;}"
        )
        blay = QVBoxLayout(btn_col)
        blay.setContentsMargins(12, 12, 12, 12)
        blay.setSpacing(12)

        self.btn_continue = QPushButton("Continue")
        self.btn_continue.setMinimumHeight(76)
        self.btn_continue.setStyleSheet(self._btn_purple())
        self.btn_continue.clicked.connect(self._on_continue_clicked)
        blay.addWidget(self.btn_continue)

        self.btn_hold = QPushButton("Hold")
        self.btn_hold.setMinimumHeight(76)
        self.btn_hold.setStyleSheet(self._btn_purple())
        self.btn_hold.clicked.connect(self._on_hold_clicked)
        blay.addWidget(self.btn_hold)

        self.btn_abort = QPushButton("Abort")
        self.btn_abort.setMinimumHeight(76)
        self.btn_abort.setStyleSheet(self._btn_purple())
        self.btn_abort.clicked.connect(self._on_abort_clicked)
        blay.addWidget(self.btn_abort)

        self.btn_manual_auto = QPushButton("Manual/Auto")
        self.btn_manual_auto.setMinimumHeight(76)
        self.btn_manual_auto.setStyleSheet(self._btn_purple())
        self.btn_manual_auto.clicked.connect(self._on_manual_auto_clicked)
        blay.addWidget(self.btn_manual_auto)

        self.btn_start_recording = QPushButton("Start Recording")
        self.btn_start_recording.setMinimumHeight(76)
        self.btn_start_recording.setStyleSheet(
            """
            QPushButton{
                background:#2e7d32;
                color:white;
                border:none;
                border-radius:10px;
                font-size:16px;
                font-weight:800;
            }
            QPushButton:hover{ background:#1b5e20; }
            QPushButton:pressed{ background:#174f1a; }
            QPushButton:disabled{ background:#555; color:#bbb; }
            """
        )
        self.btn_start_recording.setToolTip("Start a new recording run")
        self.btn_start_recording.clicked.connect(self._on_start_recording_clicked)
        blay.addWidget(self.btn_start_recording)

        self.btn_stop_recording = QPushButton("Stop Recording")
        self.btn_stop_recording.setMinimumHeight(76)
        self.btn_stop_recording.setStyleSheet(
            """
            QPushButton{
                background:#c62828;
                color:white;
                border:none;
                border-radius:10px;
                font-size:16px;
                font-weight:800;
            }
            QPushButton:hover{ background:#b71c1c; }
            QPushButton:disabled{ background:#555; color:#bbb; }
            """
        )
        self.btn_stop_recording.setToolTip("Stop the active recording and finish the run")
        self.btn_stop_recording.clicked.connect(self._on_stop_recording_clicked)
        self.btn_stop_recording.setEnabled(False)
        blay.addWidget(self.btn_stop_recording)

        blay.addStretch(1)
        return btn_col

    def _create_live_right_controller_area(self) -> QWidget:
        outer = QWidget()
        outer_layout = QHBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(8)

        main_stack = self._create_live_right_content_stack()
        btn_col = self._create_button_column()

        outer_layout.addWidget(main_stack, 1)
        outer_layout.addWidget(btn_col, 0)
        return outer

    def _create_playback_right_controller_area(self) -> QWidget:
        return self._create_playback_right_content_stack()

    def _panel(self, title: str, widget: QWidget) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame{background:#202020; border:1px solid #444; border-radius:10px;}"
        )
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        head = QLabel(title)
        head.setStyleSheet(
            """
            QLabel{
                background:#2a2a2a;
                color:#fff;
                padding:10px;
                border-top-left-radius:10px;
                border-top-right-radius:10px;
                font-weight:bold;
            }
        """
        )
        v.addWidget(head)

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.addWidget(widget)
        v.addWidget(body, 1)
        return panel

    # =========================================================
    # Badge / Styles
    # =========================================================
    def _set_badge(self, label: QLabel, text: str, bg: str, fg: str, big: bool):
        label.setText(text)
        pad = "6px 12px" if big else "4px 10px"
        fs = "18px" if big else "12px"
        label.setStyleSheet(
            f"""
            QLabel {{
                background: {bg};
                color: {fg};
                padding: {pad};
                border-radius: 10px;
                font-size: {fs};
                font-weight: 800;
            }}
        """
        )

    def _btn_purple(self) -> str:
        return """
            QPushButton{
                background:#8e24aa;
                color:white;
                border:none;
                border-radius:10px;
                font-size:16px;
                font-weight:800;
            }
            QPushButton:hover{ background:#7b1fa2; }
            QPushButton:pressed{ background:#6a1b9a; }
            QPushButton:disabled{ background:#555; color:#bbb; }
        """

    # =========================================================
    # Public setters
    # =========================================================
    def set_status(self, key: str):
        text, bg, fg = self.STATUS_STYLE.get(
            key.lower().strip(), self.STATUS_STYLE["idle"]
        )
        self._set_badge(self.status_badge, text, bg, fg, big=True)

    def set_health(self, key: str):
        text, bg, fg = self.HEALTH_STYLE.get(
            key.lower().strip(), self.HEALTH_STYLE["default"]
        )
        self._set_badge(self.health_badge, text, bg, fg, big=True)

    def set_mode(self, key: str):
        text, bg, fg = self.MODE_STYLE.get(key.lower().strip(), self.MODE_STYLE["auto"])
        self._set_badge(self.mode_badge, text, bg, fg, big=False)

    def set_script_state(self, key: str):
        text, bg, fg = self.SCRIPT_STYLE.get(
            key.lower().strip(), self.SCRIPT_STYLE["idle"]
        )
        self._set_badge(self.script_badge, text, bg, fg, big=False)

    def set_stages(self, prev: str, current: str, next_: str):
        self.stage_prev._value_label.setText(prev)
        self.stage_curr._value_label.setText(current)
        self.stage_next._value_label.setText(next_)

    # Engine force update API
    def set_engine_sensors(self, up=None, right=None, down=None, left=None):
        self.engine_force_widget.set_sensors(up, right, down, left)

    # Telemetry update API
    def set_tank_telemetry(
        self,
        tank: str,
        pressure_psi=None,
        temp_c=None,
        level_pct=None,
        valve_open_pct=None,
    ):
        t = (tank or "").strip().lower()
        if t == "ipa":
            self.telemetry_widget.set_ipa(
                pressure_psi, temp_c, level_pct, valve_open_pct
            )
        elif t == "lox":
            self.telemetry_widget.set_lox(
                pressure_psi, temp_c, level_pct, valve_open_pct
            )

    def set_tank_info(self, text: str):
        self.telemetry_widget.set_info(text)

    def _on_tank_clicked(self, name: str):
        self.set_tank_info(f"{name} tank selected. (put more details here)")

    def handle_playback_loaded(self, payload: dict):
        if not self.playback_mode:
            return

        if not isinstance(payload, dict):
            return

        duration_seconds = payload.get("duration_seconds")
        if isinstance(duration_seconds, (int, float)):
            self.playback_duration_seconds = max(0.0, float(duration_seconds))
            self.timeline.set_total_duration(self.playback_duration_seconds)

        metadata = payload.get("metadata", {})
        run_id = payload.get("run_id")
        if isinstance(metadata, dict):
            test_name = metadata.get("test_name") or payload.get("run_id")
            run_id = metadata.get("run_id") or run_id
            if test_name:
                self.setWindowTitle(f"minTS Controller - Playback - {test_name}")

        if self.playback_mode:
            provider = getattr(self, "graph_provider", None)
            if provider is not None:
                try:
                    provider.load_from_payload(payload)
                except Exception:
                    self.log.exception("Failed to load playback graph provider")
            self.console.load_playback_run(run_id=run_id, metadata=metadata if isinstance(metadata, dict) else None)
            self.console.set_playback_time(self.playback_time)
            self._refresh_aux_clock_display()
            if isinstance(self.playback_duration_seconds, (int, float)):
                self.timeline.set_total_duration(self.playback_duration_seconds)
            self.timeline.set_current_time(max(0.0, float(self.playback_time)))
            self._sync_playback_graph_provider_window()

        self._refresh_aux_clock_display()

    def handle_backend_status(self, payload: dict):
        if not isinstance(payload, dict):
            return

        mission_clock = payload.get("mission_clock")
        recording = payload.get("recording")
        playback_clock = payload.get("playback_clock")

        self._backend_mission_clock = dict(mission_clock) if isinstance(mission_clock, dict) else self._backend_mission_clock
        self._backend_recording_clock = dict(recording) if isinstance(recording, dict) else self._backend_recording_clock
        self._backend_playback_clock = dict(playback_clock) if isinstance(playback_clock, dict) else self._backend_playback_clock

        run_mode = payload.get("run_mode")
        if isinstance(run_mode, str) and run_mode.strip().lower() == "playback":
            self.set_mode("playback")

        self._update_time_displays()


    def handle_script_status(self, payload: dict):
        scripter = getattr(self, "scripter", None)
        handler = getattr(scripter, "handle_script_status", None)
        if callable(handler):
            handler(dict(payload))

    def apply_backend_state_snapshot(self, snapshot: dict):
        if not isinstance(snapshot, dict):
            return
        self._last_backend_snapshot = dict(snapshot)

        provider = getattr(self, "graph_provider", None)
        if provider is not None and not self.playback_mode:
            try:
                provider.ingest_state_snapshot(snapshot)
            except Exception:
                self.log.exception("Failed to ingest live graph snapshot")

        mission_clock = snapshot.get("mission_clock")
        recording_clock = snapshot.get("recording_clock")
        playback_clock = snapshot.get("playback_clock")

        self._backend_mission_clock = dict(mission_clock) if isinstance(mission_clock, dict) else self._backend_mission_clock
        self._backend_recording_clock = dict(recording_clock) if isinstance(recording_clock, dict) else self._backend_recording_clock
        self._backend_playback_clock = dict(playback_clock) if isinstance(playback_clock, dict) else self._backend_playback_clock

        self._recording_started_dt = self._parse_recording_start_time(recording_clock)

        if isinstance(playback_clock, dict):
            total_duration_seconds = playback_clock.get("total_duration_seconds")
            if isinstance(total_duration_seconds, (int, float)):
                self.playback_duration_seconds = max(0.0, float(total_duration_seconds))
                self.timeline.set_total_duration(self.playback_duration_seconds)

            position_seconds = playback_clock.get("position_seconds")
            if isinstance(position_seconds, (int, float)):
                self.playback_time = max(0.0, float(position_seconds))

        self._update_time_displays()
        if self.playback_mode:
            self._sync_playback_graph_provider_window()
        self._sync_recording_buttons(snapshot)

        scripter = getattr(self, "scripter", None)
        script_snapshot_handler = getattr(scripter, "apply_backend_state_snapshot", None)
        if callable(script_snapshot_handler):
            script_snapshot_handler(dict(snapshot))

    def handle_structured_event(self, payload: dict):
        provider = getattr(self, "graph_provider", None)
        if provider is None or not isinstance(payload, dict):
            return
        if self.playback_mode:
            return
        try:
            provider.ingest_structured_event(payload)
        except Exception:
            self.log.exception("Failed to ingest live graph structured event")

    def handle_playback_seek_bootstrap(self, payload: dict):
        if not self.playback_mode:
            return
        self._sync_playback_graph_provider_window()

    def _playback_graph_window_bounds(self) -> tuple[float, float]:
        end_ts = max(0.0, float(self.playback_time))
        start_ts = max(0.0, end_ts - float(self.graph.duration))
        return start_ts, end_ts

    def _sync_playback_graph_provider_window(self) -> None:
        if not self.playback_mode:
            return
        provider = getattr(self, "graph_provider", None)
        if provider is None:
            return
        setter = getattr(provider, "set_time_window", None)
        if not callable(setter):
            return
        start_ts, end_ts = self._playback_graph_window_bounds()
        setter(start_ts=start_ts, end_ts=end_ts)

    def _set_aux_clock_display(self, text: str, *, accent: str = "neutral"):
        fg, bg = self.AUX_CLOCK_STYLE.get(accent, self.AUX_CLOCK_STYLE["neutral"])
        self.aux_time_label.setText(text)
        self.aux_time_label.setStyleSheet(
            f"color:{fg}; background:{bg}; border:none; padding:0 12px 2px 12px;"
        )

    def _format_short_duration(self, total_seconds: float | None) -> str:
        if total_seconds is None:
            return "--"

        total_seconds = max(0, int(round(float(total_seconds))))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours:d}h {minutes:02d}m {seconds:02d}s"
        return f"{minutes:d}m {seconds:02d}s"

    def _format_precise_duration(self, total_seconds: float | None) -> str:
        if total_seconds is None:
            return "--:--.---"

        total_seconds = max(0.0, float(total_seconds))
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        milliseconds = int((total_seconds % 1) * 1000)

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    def _refresh_aux_clock_display(self) -> None:
        if self.playback_mode:
            current_text = self._format_precise_duration(self.playback_time)
            total_text = self._format_precise_duration(self.playback_duration_seconds)
            self._set_aux_clock_display(
                f"Playback {current_text} / {total_text}",
                accent="playback",
            )
            return

        recording_clock = self._backend_recording_clock if isinstance(self._backend_recording_clock, dict) else {}
        active = bool(recording_clock.get("active"))

        # When recording is active and we have an authoritative start time,
        # compute elapsed locally so the 100ms display timer advances smoothly
        # between backend snapshot polls (~3s).
        if active and self._recording_started_dt is not None:
            elapsed = (datetime.now(self._recording_started_dt.tzinfo) - self._recording_started_dt).total_seconds()
            elapsed = max(0.0, elapsed)
            self._set_aux_clock_display(
                f"Recording: {self._format_short_duration(elapsed)}",
                accent="recording",
            )
            return

        # Fallback: use backend-provided display_text for non-active states
        # (stopped/completed/idle).
        display_text = recording_clock.get("display_text")
        if isinstance(display_text, str) and display_text.strip():
            self._set_aux_clock_display(
                display_text.strip(),
                accent="recording" if active else "neutral",
            )
            return

        self._set_aux_clock_display("Not Recording", accent="neutral")

    # =========================================================
    # Timer update
    # =========================================================
    def _update_time_displays(self):
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S"))

        mission_seconds = None
        if isinstance(self._backend_mission_clock, dict):
            backend_seconds = self._backend_mission_clock.get("seconds")
            if isinstance(backend_seconds, (int, float)):
                mission_seconds = float(backend_seconds)

        if self.playback_mode:
            playback_seconds = self.playback_time
            if isinstance(self._backend_playback_clock, dict):
                backend_position = self._backend_playback_clock.get("position_seconds")
                if isinstance(backend_position, (int, float)):
                    playback_seconds = max(0.0, float(backend_position))
                    self.playback_time = playback_seconds

                backend_total = self._backend_playback_clock.get("total_duration_seconds")
                if isinstance(backend_total, (int, float)):
                    self.playback_duration_seconds = max(0.0, float(backend_total))
                    self.timeline.set_total_duration(self.playback_duration_seconds)

            self._update_mission_time_label(playback_seconds)
            self.timeline.set_current_time(playback_seconds)
            self.console.set_playback_time(playback_seconds)
            self._sync_playback_graph_provider_window()
        elif mission_seconds is not None:
            self._update_mission_time_label(mission_seconds)
            self.timeline.set_current_time(max(0.0, mission_seconds))
        elif self.mission_running and self.mission_start_time:
            elapsed = datetime.now() - self.mission_start_time
            total_seconds = elapsed.total_seconds()
            self._update_mission_time_label(total_seconds)
            self.timeline.set_current_time(total_seconds)
        else:
            self._update_mission_time_label(0.0)
            if not self.playback_mode:
                self.timeline.set_current_time(0.0)

        self._refresh_aux_clock_display()

    def _update_mission_time_label(self, total_seconds: float):
        abs_seconds = abs(float(total_seconds))
        hours = int(abs_seconds // 3600)
        minutes = int((abs_seconds % 3600) // 60)
        seconds = int(abs_seconds % 60)
        milliseconds = int((abs_seconds % 1) * 1000)

        if self.playback_mode:
            # Playback keeps the script clock as a placeholder for now;
            # duration lives in the blue subtitle instead.
            self.mission_time_label.setText("00:00:00.000")
            return

        sign = "+" if total_seconds >= 0 else "-"
        self.mission_time_label.setText(
            f"T{sign}{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
        )

    def _on_playback_shortcut(self):
        if not self.playback_mode:
            return
        focus = QApplication.focusWidget()
        if isinstance(focus, (QSpinBox, QDoubleSpinBox)):
            return
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit)) and not focus.isReadOnly():
            return
        self._toggle_playback()

    def _step_playback_speed(self, direction: int) -> None:
        psm = self._playback_state_manager
        if psm is not None:
            new_speed = psm.step_speed(direction)
            self.log.info("Playback speed set to %.2fx", new_speed)
            return
        steps = list(self._playback_speed_steps)
        try:
            current_index = steps.index(self._playback_speed)
        except ValueError:
            current_index = steps.index(1.0)
        next_index = min(max(current_index + int(direction), 0), len(steps) - 1)
        self._playback_speed = float(steps[next_index])
        self.log.info("Playback speed set to %.2fx", self._playback_speed)

    def _toggle_playback(self):
        if not self.playback_mode:
            return
        psm = self._playback_state_manager
        if psm is not None:
            if psm.is_playing:
                exact_time = psm.pause()
                self.timeline.set_current_time(exact_time)
                self._update_mission_time_label(exact_time)
                self.console.set_playback_time(exact_time)
                self._refresh_aux_clock_display()
                self._playback_advance_timer.stop()
            else:
                if not psm.start_playing():
                    return  # at end
                self._playback_advance_timer.start()
            return
        # Legacy fallback (no manager)
        if self._playback_running:
            exact_time = self._playback_anchor + (time.monotonic() - self._playback_mono_start)
            duration = self.playback_duration_seconds
            if isinstance(duration, (int, float)) and duration > 0:
                exact_time = min(exact_time, duration)
            self.playback_time = exact_time
            self.timeline.set_current_time(exact_time)
            self._update_mission_time_label(exact_time)
            self.console.set_playback_time(exact_time)
            self._refresh_aux_clock_display()
            self._playback_running = False
            self._playback_advance_timer.stop()
        else:
            duration = self.playback_duration_seconds
            if isinstance(duration, (int, float)) and duration > 0 and self.playback_time >= duration:
                return
            self._playback_anchor = self.playback_time
            self._playback_mono_start = time.monotonic()
            self._playback_running = True
            self._playback_advance_timer.start()

    def _on_playback_advance(self):
        psm = self._playback_state_manager
        if psm is not None:
            if not psm.is_playing:
                self._playback_advance_timer.stop()
                return

            previous_time = psm.position_seconds
            new_time = psm.compute_advance_time()

            if psm.duration_seconds > 0 and new_time >= psm.duration_seconds:
                new_time = psm.duration_seconds
                psm.is_playing = False
                self._playback_advance_timer.stop()

            advance_handler = getattr(self.manager, "playback_advance_handler", None)
            if callable(advance_handler):
                advance_handler(previous_time, new_time)
                return

            psm.set_position(new_time)
            self.timeline.set_current_time(new_time)
            self._update_mission_time_label(new_time)
            self.console.set_playback_time(new_time)
            self._refresh_aux_clock_display()

            handler = getattr(self.manager, "playback_seek_handler", None)
            if callable(handler):
                handler(new_time)
            return

        # Legacy fallback (no manager)
        if not self._playback_running:
            self._playback_advance_timer.stop()
            return

        previous_time = float(self.playback_time)
        elapsed = time.monotonic() - self._playback_mono_start
        new_time = self._playback_anchor + (elapsed * float(self._playback_speed))
        duration = self.playback_duration_seconds

        if isinstance(duration, (int, float)) and duration > 0 and new_time >= duration:
            new_time = duration
            self._playback_running = False
            self._playback_advance_timer.stop()

        advance_handler = getattr(self.manager, "playback_advance_handler", None)
        if callable(advance_handler):
            advance_handler(previous_time, new_time)
            return

        self.playback_time = new_time
        self.timeline.set_current_time(new_time)
        self._update_mission_time_label(new_time)
        self.console.set_playback_time(new_time)
        self._refresh_aux_clock_display()

        handler = getattr(self.manager, "playback_seek_handler", None)
        if callable(handler):
            handler(new_time)

    def _on_timeline_seek(self, seek_time: float):
        # Manual scrub pauses playback so the timer doesn't fight the user
        psm = self._playback_state_manager
        if psm is not None and psm.is_playing:
            psm.pause()
            self._playback_advance_timer.stop()
        elif self._playback_running:
            self._playback_running = False
            self._playback_advance_timer.stop()

        handler = getattr(self.manager, "playback_seek_handler", None)
        if callable(handler):
            handler(seek_time)
            return

        self.playback_time = seek_time
        self.timeline.set_current_time(seek_time)
        self._update_mission_time_label(seek_time)
        self.console.set_playback_time(seek_time)
        self._refresh_aux_clock_display()

    def set_playback_time(self, seek_time: float):
        self.playback_time = max(0.0, float(seek_time))
        self.timeline.set_current_time(self.playback_time)
        self._update_mission_time_label(self.playback_time)
        self.console.set_playback_time(self.playback_time)
        self._refresh_aux_clock_display()
        self._sync_playback_graph_provider_window()

    # =========================================================
    # Buttons (placeholder behavior)
    # =========================================================
    def _on_continue_clicked(self):
        if self.playback_mode:
            return
        self.set_status("normal")
        self.set_script_state("running")

    def _on_hold_clicked(self):
        if self.playback_mode:
            return
        self.set_status("hold")
        self.set_script_state("pause")

    def _on_abort_clicked(self):
        if self.playback_mode:
            return
        self.set_status("abort")
        self.set_script_state("pause")
        self.abort()

    def _on_manual_auto_clicked(self):
        if self.playback_mode:
            return
        cur = self.mode_badge.text().lower()
        self.set_mode("manual" if cur == "auto" else "auto")

    def _on_start_recording_clicked(self):
        if self.playback_mode:
            return
        start = getattr(self, "start_backend_run", None)
        if callable(start):
            self.log.info("Operator requested start recording via controller button")
            self.btn_start_recording.setEnabled(False)
            try:
                start()
            except Exception:
                self.log.exception("Failed to request backend start_run")
                self.btn_start_recording.setEnabled(True)
        else:
            self.log.warning("start_backend_run not available - backend bridge may not be attached")

    def _on_stop_recording_clicked(self):
        if self.playback_mode:
            return
        finish = getattr(self, "finish_backend_run", None)
        if callable(finish):
            self.log.info("Operator requested stop recording via controller button")
            self.btn_stop_recording.setEnabled(False)
            try:
                finish(reason="operator_stop")
            except Exception:
                self.log.exception("Failed to request backend finish_run")
                self.btn_stop_recording.setEnabled(True)
        else:
            self.log.warning("finish_backend_run not available - backend bridge may not be attached")

    def _sync_recording_buttons(self, snapshot: dict) -> None:
        """Update Start/Stop Recording button states from backend run state."""
        btn_start = getattr(self, "btn_start_recording", None)
        btn_stop = getattr(self, "btn_stop_recording", None)
        if btn_start is None or btn_stop is None:
            return
        run = snapshot.get("run")
        is_running = isinstance(run, dict) and run.get("is_running")
        consumed = isinstance(run, dict) and run.get("recording_session_consumed")
        btn_start.setEnabled(not is_running and not consumed)
        btn_stop.setEnabled(is_running)
        if consumed and not is_running:
            btn_start.setText("Recording Done")
            btn_start.setToolTip("Recording session complete - restart for a new run")
        else:
            btn_start.setText("Start Recording")
            btn_start.setToolTip("Start a new recording run")

    @staticmethod
    def _parse_recording_start_time(recording_clock) -> datetime | None:
        """Extract and parse the authoritative recording start time from a
        backend recording_clock snapshot section.

        Returns a timezone-aware datetime if ``recording_clock.active`` is
        truthy and ``started_wall_time`` is a valid ISO-8601 timestamp, or
        ``None`` otherwise.
        """
        if not isinstance(recording_clock, dict):
            return None
        if not recording_clock.get("active"):
            return None
        raw = recording_clock.get("started_wall_time")
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            text = raw.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return datetime.fromisoformat(text)
        except (ValueError, TypeError):
            return None

    def _on_device_requested(self, device_id: str, target_card=None):
        meta = self.device_meta.get(device_id)
        device = self.devices.get(device_id)

        if meta is None or device is None:
            self.log.warning(f"Requested unknown device: {device_id}")
            return

        if not meta.get("isActive", False):
            self.log.info(f"Ignoring inactive device request: {device_id}")
            return

        if not meta.get("hasElectricalIO", False):
            self.log.info(f"Ignoring mechanical device request: {device_id}")
            return

        if self.workspace.add_graph_device(device, target_card=target_card):
            if target_card is None:
                self.log.info(f"Added active signal device to new graph widget: {device_id}")
            else:
                self.log.info(f"Added active signal device to existing graph widget: {device_id}")
        else:
            self.log.info(f"Workspace request was ignored for device: {device_id}")

    # =========================================================
    # Device hooks
    # =========================================================
    def addDevice(self, device, meta: dict):
        device_id = meta["id"]

        self.devices[device_id] = device
        self.device_meta[device_id] = meta

        if meta.get("isActive", False) and meta.get("hasElectricalIO", False):
            self.exporter.devices.append(device)

        self.device_library.add_device(meta)

    def abort(self):
        self.log.fatal("Abort triggered! Slap the big red button NOW!")
