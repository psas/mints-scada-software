"""gui/view_export.py

Export view for writing per-device CSV files from the GUI.

This widget currently exposes a single folder-based export action that writes a
CSV file for each device in ``self.devices`` that is a ``GenericSensor``.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QFileDialog
from nexus import GenericSensor
import csv
import os
import logging


class ExportView(QWidget):
    """Simple export panel for writing device CSV files.

    The view owns a push button that opens a directory chooser and exports one
    CSV file per sensor-like device currently present in ``self.devices``.
    """

    def __init__(self):
        """Initialize the export view and its single export action."""
        super().__init__()
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.devices = []

        self.log = logging.getLogger("export")

        self.savebutton = QPushButton("Export all files")
        self.savebutton.clicked.connect(self._export)

        self.layout.addWidget(self.savebutton)
        self.layout.addStretch()

    def _export(self):
        """Open a folder chooser and write placeholder CSV exports for sensors.

        The export currently iterates over ``self.devices`` and writes a CSV
        file for each entry that is a ``GenericSensor``. The output filename is
        based on ``device.device_id`` when present, or ``unknown_device`` as a
        fallback.

        Returns:
            None.
        """
        self.log.info("Time to export!")
        dialog = QFileDialog()
        folder_path = dialog.getExistingDirectory(None, "Select Folder")

        for device in self.devices:
            if isinstance(device, GenericSensor):
                device_id = getattr(device, "device_id", "unknown_device")
                path = os.path.join(folder_path, f"{device_id}.csv")
                with open(path, "w") as csvfile:
                    self.log.debug(f"Saving CSV {path}")
                    spamwriter = csv.writer(
                        csvfile, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL
                    )
                    spamwriter.writerow(["Spam"] * 5 + ["Baked Beans"])
                    spamwriter.writerow(["Spam", "Lovely Spam", "Wonderful Spam"])

        self.log.info(f"Exporting to {folder_path}")
