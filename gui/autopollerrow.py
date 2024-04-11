from PyQt5.QtWidgets import QPushButton, QLabel, QHBoxLayout
from gui import AutoPoller, DecadeSpinBox

class AutoPollerRow(QHBoxLayout):

    START_TEXT = "Start"
    STOP_TEXT = "Stop"
    RUNNING_TEXT = "Running"
    STOPPED_TEXT = "Stopped"

    def __init__(self, poller: AutoPoller):
        super().__init__()
        self.poller = poller
        self.poller.statusListeners["start"] = self.onStart
        self.poller.statusListeners["stop"] = self.onStop

        self.nameLabel = QLabel("Autopoller")
        self.addWidget(self.nameLabel)

        self.valueLabel = QLabel(self.STOPPED_TEXT if not self.poller.running else self.RUNNING_TEXT)
        self.addWidget(self.valueLabel)

        self.addStretch()

        self.intervalLabel = QLabel("Interval:")
        self.addWidget(self.intervalLabel)
        self.intervalbox = DecadeSpinBox()
        self.intervalbox.setFixedWidth(80)
        def onSpinBoxChange():
            self.poller.setInterval(self.intervalbox.value())
        self.intervalbox.valueChanged.connect(onSpinBoxChange)
        # self.intervalbox.setDecimals(3)
        self.intervalbox.setValue(self.poller.getInterval())
        # self.intervalbox.setValue(0.004)
        self.intervalbox.setMinimum(0.001)
        self.intervalbox.setMaximum(10)
        self.addWidget(self.intervalbox)
        self.intervalbox.setSuffix("s")

        self.measuredLabel = QLabel("")
        self.addWidget(self.measuredLabel)
        def updateAverage(poller: AutoPoller):
            self.measuredLabel.setText(f"avg: {f'{poller.getAveragePollTime():0.6f}s' if poller._avgBuffFilled else f'calc {poller._avgBuffIndex}/{poller._avgBuffSize}'}")
            # self.measuredLabel.setText(f"avg: {f'{poller._processingDelay:-0.6f}s' if poller._avgBuffFilled else f'calc {poller._avgBuffIndex}/{poller._avgBuffSize}'}")
        poller.onPoll.append(updateAverage)

        self.errLabel = QLabel("")
        self.addWidget(self.errLabel)
        def updateAverage(poller: AutoPoller):
            # self.errLabel.setText(f"err: {f'{poller.getAveragePollTime():-0.6f}s' if poller._avgBuffFilled else f'calc {poller._avgBuffIndex}/{poller._avgBuffSize}'}")
            self.errLabel.setText(f"proc:{f'{poller.getAvgProcTime():0.6f}s' if poller._avgBuffFilled else f'calc {poller._avgBuffIndex}/{poller._avgBuffSize}'}")
        poller.onPoll.append(updateAverage)

        self.addStretch()

        self.startStopButton = QPushButton(self.START_TEXT if not self.poller.running else self.STOP_TEXT)
        self.startStopButton.clicked.connect(self.buttonClick)
        self.addWidget(self.startStopButton)

    def onStart(self):
        self.valueLabel.setText(self.RUNNING_TEXT)
        self.startStopButton.setText(self.STOP_TEXT)

    def onStop(self):
        self.valueLabel.setText(self.STOPPED_TEXT)
        self.startStopButton.setText(self.START_TEXT)

    def buttonClick(self):
        if self.poller.running:
            self.poller.stop()
        else:
            self.poller.start()