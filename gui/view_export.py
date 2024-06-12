from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QFileDialog
from nexus import GenericSensor
import csv
import os
import logging

class ExportView(QWidget):
    def __init__(self):
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
        self.log.info("Time to export!")
        dialog = QFileDialog()
        folder_path = dialog.getExistingDirectory(None, "Select Folder")

        for device in self.devices:
            if isinstance(device, GenericSensor):
                device: GenericSensor = device
                path = os.path.join(folder_path, device.name + ".csv")
                with open(path, "w") as csvfile:
                    self.log.debug(f"Saving CSV {path}")
                    spamwriter = csv.writer(csvfile, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                    spamwriter.writerow(['Spam'] * 5 + ['Baked Beans'])
                    spamwriter.writerow(['Spam', 'Lovely Spam', 'Wonderful Spam'])

        self.log.info(f"Exporting to {folder_path}")