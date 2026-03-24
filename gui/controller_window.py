# controller_window.py
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QPainter, QPen, QColor, QDrag
from PyQt5.QtCore import Qt, QTimer, QRect, pyqtSignal, QMimeData, QSize

import qdarkstyle
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime

from gui import (
    GraphView,
    ExportView,
    ConsoleView,
    ScriptView,
    MintsScriptAPI,
    AutoPollerRow,
)
from gui.timelineview import TimelineView
from nexus import BusRider


DEVICE_MIME_TYPE = "application/x-mints-device-id"
SYSTEM_ORDER = {"IG": 0, "IPA": 1, "LOX": 2}


def normalize_systems(device_systems):
    if not device_systems:
        return []

    seen = set()
    ordered = []
    for s in device_systems:
        if s and s not in seen:
            seen.add(s)
            ordered.append(s)

    ordered.sort(key=lambda s: (SYSTEM_ORDER.get(s, 999), s))
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


class GraphLegendChip(QFrame):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(
            """
            QFrame {
                background: #1a1d1f;
                border: 1px solid #3b3f42;
                border-radius: 10px;
            }
            QLabel {
                color: #d9d9d9;
                border: none;
                background: transparent;
            }
        """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color}; border: none; background: transparent;")
        text = QLabel(label)
        layout.addWidget(dot, 0)
        layout.addWidget(text, 0)


class GraphWidgetCard(QFrame):
    dropDeviceRequested = pyqtSignal(str)
    settingsRequested = pyqtSignal()

    def __init__(self, state: GraphCardState, graph_widget: QWidget | None = None, parent=None):
        super().__init__(parent)
        self.state = state
        self.graph_widget = None

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

        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(2)

        self.title_label = QLabel()
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        self.title_label.setFont(title_font)

        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("color: #aab2bd; border: none; background: transparent;")

        title_block.addWidget(self.title_label)
        title_block.addWidget(self.summary_label)

        header_layout.addLayout(title_block, 1)

        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedSize(34, 30)
        self.settings_button.setToolTip("Graph widget settings will be wired in the next commit.")
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        header_layout.addWidget(self.settings_button, 0, Qt.AlignTop)

        self.main_layout.addLayout(header_layout)

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
        self.legend_layout = QHBoxLayout(self.legend_row)
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setSpacing(8)
        self.main_layout.addWidget(self.legend_row, 0)

        self._set_graph_widget(graph_widget)
        self.sync_from_state()
        self.sync_legend([])

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
        self.summary_label.setText(f"{count} {input_word} · {int(self.state.duration_s)}s")

    def sync_legend(self, entries: list[tuple[str, str]]):
        while self.legend_layout.count():
            item = self.legend_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.deleteLater()

        if not entries:
            label = QLabel("Legend will appear here when channels are graphed.")
            label.setStyleSheet("color: #8f98a3; border: none; background: transparent;")
            self.legend_layout.addWidget(label, 0)
            self.legend_layout.addStretch(1)
            return

        for name, color in entries:
            self.legend_layout.addWidget(GraphLegendChip(name, color), 0)

        self.legend_layout.addStretch(1)

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
            self.dropDeviceRequested.emit(raw)
            event.acceptProposedAction()
        else:
            event.ignore()


class GraphWorkspace(QWidget):
    deviceDropped = pyqtSignal(str)

    def __init__(self, graph_widget: QWidget, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        self.graph_widget = graph_widget
        self.graph_widget.hide()

        self._graph_device_ids = set()
        self._graph_device_order: list[str] = []
        self._device_names: dict[str, str] = {}
        self._cards: list[GraphWidgetCard] = []
        self._primary_card: GraphWidgetCard | None = None

        self.placeholder = QLabel(
            "Drag active signal devices here\n\n"
            "A scrollable graph workspace shell is ready. New graph cards will stack here."
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

        duration_changed = getattr(self.graph_widget, "durationChanged", None)
        if duration_changed is not None:
            duration_changed.connect(self._on_graph_duration_changed)

        self._refresh_empty_state()

    def _refresh_empty_state(self):
        has_cards = bool(self._cards)
        self.placeholder.setVisible(not has_cards)
        self.scroll_area.setVisible(has_cards)
        self.graph_widget.setVisible(has_cards)

    def _insert_card(self, card: GraphWidgetCard):
        self.scroll_layout.insertWidget(max(0, self.scroll_layout.count() - 1), card)

    def _default_duration(self) -> int:
        try:
            return int(getattr(self.graph_widget, "duration", 60))
        except Exception:
            return 60

    def _default_title(self) -> str:
        if not self._graph_device_order:
            return "Signal Graph"

        labels = [self._device_names.get(device_id, device_id) for device_id in self._graph_device_order]
        return ", ".join(labels)

    def _ensure_primary_card(self) -> GraphWidgetCard:
        if self._primary_card is None:
            state = GraphCardState(
                title=self._default_title(),
                device_ids=list(self._graph_device_order),
                duration_s=self._default_duration(),
            )
            self._primary_card = GraphWidgetCard(state, graph_widget=self.graph_widget)
            self._primary_card.dropDeviceRequested.connect(self.deviceDropped.emit)
            self._primary_card.settingsRequested.connect(self._on_settings_requested)
            self._cards.append(self._primary_card)
            self._insert_card(self._primary_card)

        self._refresh_empty_state()
        return self._primary_card


    def _legend_entries(self) -> list[tuple[str, str]]:
        entries = []
        sensors = getattr(self.graph_widget, "sensors", [])
        lines = getattr(self.graph_widget, "lines", [])

        for sensor, line in zip(sensors, lines):
            label = getattr(sensor, "display_name", getattr(sensor, "device_id", "Unknown"))
            color = line.get_color() if hasattr(line, "get_color") else "#d0d0d0"
            entries.append((label, color))

        return entries

    def _sync_primary_card(self):
        if self._primary_card is None:
            return

        self._primary_card.state.title = self._default_title()
        self._primary_card.state.device_ids = list(self._graph_device_order)
        self._primary_card.state.duration_s = self._default_duration()
        self._primary_card.sync_from_state()
        self._primary_card.sync_legend(self._legend_entries())

    def _on_graph_duration_changed(self, value: int):
        if self._primary_card is None:
            return

        self._primary_card.state.duration_s = int(value)
        self._primary_card.sync_from_state()

    def _on_settings_requested(self):
        log.info("Graph widget settings shell added. Wiring lands in the next commit.")

    def add_graph_device(self, device):
        device_id = getattr(device, "device_id", None)
        if not device_id or device_id in self._graph_device_ids:
            self._sync_primary_card()
            self._refresh_empty_state()
            return False

        self.graph_widget.addSensor(device, True)
        self._graph_device_ids.add(device_id)
        self._graph_device_order.append(device_id)
        self._device_names[device_id] = getattr(device, "display_name", device_id)

        card = self._ensure_primary_card()
        card.state.title = self._default_title()
        card.state.device_ids = list(self._graph_device_order)
        card.state.duration_s = self._default_duration()
        card.sync_from_state()
        card.sync_legend(self._legend_entries())

        self.graph_widget.show()
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
            self.deviceDropped.emit(raw)
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

        logging.getLogger("qdarkstyle").setLevel(logging.ERROR)
        self.log = logging.getLogger("controller_window")

        self.autopoller = autopoller
        self.playback_mode = playback_mode
        self.test_name = test_name

        self.devices: dict[str, object] = {}
        self.device_meta: dict[str, dict] = {}

        self.mission_start_time = None
        self.mission_running = False
        self.playback_time = 0.0
        self.playback_duration_seconds = None

        self._backend_mission_clock = None
        self._backend_recording_clock = None
        self._backend_playback_clock = None

        self.setWindowTitle("minTS Controller - Left Screen")

        QApplication.setStyle("Fusion")
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt5"))
        self.setFont(QFont("Arial", 10))

        # ====== Application widgets ======
        self.timeline = TimelineView(
            playback_mode=self.playback_mode,
            show_event_columns=False,
            embedded=True,
        )
        self.timeline.stage_changed.connect(self.set_stages)
        if self.playback_mode:
            self.timeline.seek_requested.connect(self._on_timeline_seek)

        self.graph = GraphView()
        self.console = ConsoleView(loghandler, playback_mode=self.playback_mode)
        self.exporter = ExportView()

        self.device_library = DeviceLibraryPanel()
        self.workspace = GraphWorkspace(self.graph)
        self.workspace.deviceDropped.connect(self._on_device_requested)
        self.device_library.deviceActivated.connect(self._on_device_requested)

        self.scripter = ScriptView(
            MintsScriptAPI(
                devices=self.devices,
                graph=self.graph,
                exporter=self.exporter,
                autopoller=self.autopoller,
                abort=self.abort,
            )
        )

        # Engine force widget
        self.engine_force_widget = EngineForceWidget(dot_gain=0.90)
        self.engine_force_widget.set_sensors(None, None, None, None)

        # Telemetry widget
        self.telemetry_widget = TelemetryWidget()
        self.telemetry_widget.tank_clicked.connect(self._on_tank_clicked)

        # ====== UI ======
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

        # Make the LEFT main window area and the RIGHT (Logs/controls) column draggable
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

        # ====== Timers ======
        self.display_timer = QTimer(self)
        self.display_timer.timeout.connect(self._update_time_displays)
        self.display_timer.start(100)

        # Initial state
        self.set_status("idle" if not self.playback_mode else "hold")
        self.set_health("default" if not self.playback_mode else "ok")
        self.set_mode("playback" if self.playback_mode else "auto")
        self.set_script_state("idle" if not self.playback_mode else "pause")
        self.set_stages("Prev", "Current", "Next")

    def closeEvent(self, event):
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
    # Right column:
    # - Top: Logs (big)
    # - Bottom row: Fuel Capacity (left) | Script area (right)
    #   Script area split vertically:
    #   - Top: Script Control
    #   - Bottom: Engine Force
    # =========================================================
    def _create_right_controller_area(self) -> QWidget:
        outer = QWidget()
        outer_layout = QHBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(8)

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

        # Button column
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

        if self.playback_mode:
            for _btn in (self.btn_continue, self.btn_hold, self.btn_abort, self.btn_manual_auto):
                _btn.setEnabled(False)
                _btn.setToolTip("Playback mode is view-only")

        blay.addStretch(1)

        outer_layout.addWidget(main_stack, 1)
        outer_layout.addWidget(btn_col, 0)
        return outer

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
            self.console.load_playback_run(run_id=run_id, metadata=metadata if isinstance(metadata, dict) else None)
            self.console.set_playback_time(self.playback_time)
            self._refresh_aux_clock_display()
            if isinstance(self.playback_duration_seconds, (int, float)):
                self.timeline.set_total_duration(self.playback_duration_seconds)
            self.timeline.set_current_time(max(0.0, float(self.playback_time)))

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

    def apply_backend_state_snapshot(self, snapshot: dict):
        if not isinstance(snapshot, dict):
            return

        mission_clock = snapshot.get("mission_clock")
        recording_clock = snapshot.get("recording_clock")
        playback_clock = snapshot.get("playback_clock")

        self._backend_mission_clock = dict(mission_clock) if isinstance(mission_clock, dict) else self._backend_mission_clock
        self._backend_recording_clock = dict(recording_clock) if isinstance(recording_clock, dict) else self._backend_recording_clock
        self._backend_playback_clock = dict(playback_clock) if isinstance(playback_clock, dict) else self._backend_playback_clock

        if isinstance(playback_clock, dict):
            total_duration_seconds = playback_clock.get("total_duration_seconds")
            if isinstance(total_duration_seconds, (int, float)):
                self.playback_duration_seconds = max(0.0, float(total_duration_seconds))
                self.timeline.set_total_duration(self.playback_duration_seconds)

            position_seconds = playback_clock.get("position_seconds")
            if isinstance(position_seconds, (int, float)):
                self.playback_time = max(0.0, float(position_seconds))

        self._update_time_displays()

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
        display_text = recording_clock.get("display_text")
        active = bool(recording_clock.get("active"))
        if isinstance(display_text, str) and display_text.strip():
            self._set_aux_clock_display(
                display_text.strip(),
                accent="recording" if active else "neutral",
            )
            return

        elapsed_seconds = recording_clock.get("elapsed_seconds")
        if active and isinstance(elapsed_seconds, (int, float)):
            self._set_aux_clock_display(
                f"Recording: {self._format_short_duration(float(elapsed_seconds))}",
                accent="recording",
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

    def _on_timeline_seek(self, seek_time: float):
        self.playback_time = seek_time
        self.timeline.set_current_time(seek_time)
        self._update_mission_time_label(seek_time)
        self.console.set_playback_time(seek_time)
        self._refresh_aux_clock_display()

        handler = getattr(self.manager, "playback_seek_handler", None)
        if callable(handler):
            handler(seek_time)

    def set_playback_time(self, seek_time: float):
        self.playback_time = max(0.0, float(seek_time))
        self.timeline.set_current_time(self.playback_time)
        self._update_mission_time_label(self.playback_time)
        self.console.set_playback_time(self.playback_time)
        self._refresh_aux_clock_display()

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

    def _on_device_requested(self, device_id: str):
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

        if self.workspace.add_graph_device(device):
            self.log.info(f"Added active signal device to workspace: {device_id}")
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
