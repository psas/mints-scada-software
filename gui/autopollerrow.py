from PyQt5.QtWidgets import QPushButton, QLabel, QHBoxLayout
from PyQt5.QtCore import QTimer, pyqtSignal
from gui import AutoPoller, DecadeSpinBox

import logging
log = logging.getLogger("autopoller.gui")

class AutoPollerRow(QHBoxLayout):

    # GUI text
    START_TEXT = "Start"
    STOP_TEXT = "Stop"
    RUNNING_TEXT = "Running"
    STOPPED_TEXT = "Stopped"

    externalChange = pyqtSignal()

    def __init__(self, poller: AutoPoller):
        super().__init__()
        self.poller = poller
        # Connect listeners to keep button status updated
        self.poller.statusListeners["start"] = self.onStart
        self.poller.statusListeners["stop"] = self.onStop

        # Row label
        self.nameLabel = QLabel("Autopoller")
        self.addWidget(self.nameLabel)

        self.valueLabel = QLabel(self.STOPPED_TEXT if not self.poller.running else self.RUNNING_TEXT)
        self.addWidget(self.valueLabel)

        self.addStretch()

        # Interval time selector
        self.intervalLabel = QLabel("Interval:")
        self.addWidget(self.intervalLabel)

        self.intervalbox = DecadeSpinBox()
        self.intervalbox.setValue(self.poller.getInterval())
        self.intervalbox.setFixedWidth(80)
        def onSpinBoxChange():
            self.poller.setInterval(self.intervalbox.value())
        self.intervalbox.valueChanged.connect(onSpinBoxChange)
        self.intervalbox.setMinimum(0.001)
        self.intervalbox.setMaximum(10)
        self.intervalbox.setSuffix("s")
        self.addWidget(self.intervalbox)

        # Interval statistics
        self.measuredLabel = QLabel("")
        self.addWidget(self.measuredLabel)

        self.errLabel = QLabel("")
        self.addWidget(self.errLabel)
        
        # Update interval statistics every 100ms
        def updateAverages():
            self.measuredLabel.setText(f"avg: {f'{self.poller.getAveragePollTime():0.6f}s' if self.poller.avgBuffFilled else f'calc {self.poller._avgBuffIndex}/{self.poller.avgBuffSize}'}")
            self.errLabel.setText(f"proc:{f'{self.poller.getAvgProcTime():0.6f}s' if self.poller.avgBuffFilled else f'calc {self.poller._avgBuffIndex}/{self.poller.avgBuffSize}'}")
        self.updateTimer = QTimer(self)
        self.updateTimer.timeout.connect(updateAverages)
        self.updateTimer.start(100)

        self.addStretch()

        # Start/stop button
        self.startStopButton = QPushButton(self.START_TEXT if not self.poller.running else self.STOP_TEXT)
        self.startStopButton.clicked.connect(self.buttonClick)
        self.addWidget(self.startStopButton)

        self.poller.setIntervalChangeListener(self.externalChange.emit)
        self.externalChange.connect(self.onExternalChangeSignal)

    def onStart(self):
        ''' Called when the autopoller starts '''
        self.valueLabel.setText(self.RUNNING_TEXT)
        self.startStopButton.setText(self.STOP_TEXT)

    def onStop(self):
        ''' Called when the autopoller stops '''
        self.valueLabel.setText(self.STOPPED_TEXT)
        self.startStopButton.setText(self.START_TEXT)

    def buttonClick(self):
        ''' Called when the start/stop button is clicked '''
        if self.poller.running:
            self.poller.stop()
        else:
            self.poller.start()

    def onExternalChangeSignal(self):
        self.intervalbox.setValue(self.poller.getInterval())