from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit
from PyQt5.QtCore import Qt, pyqtSignal
import logging
import threading
from gui import MintsScriptAPI
import os

################################
#
#   IMPORTANT NOTE
#
# This method of running the code assumes that we trust the user's code
# This is not generally a good idea, however it is much simpler than trying
#   to properly sandbox it while still giving it access to what it needs.
# Since the rest of the program already runs as the user, I'm not too worried about it.   
#
################################

class ScriptView(QWidget):
    START_BUTTON_TEXT = "Run Script"
    STOP_BUTTON_TEXT = "Kill Script"

    # This has to go here, not in the constructor. Not sure why, but this works.
    doneSignal = pyqtSignal()

    def __init__(self, mintsapi):
        super().__init__()
        self.log = logging.getLogger("script")
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.layout.setAlignment(Qt.AlignTop)

        self.runner = None
        self.running = threading.Event()

        self.doneSignal.connect(self._done)

        self.statusLayout = QHBoxLayout()
        self.layout.addLayout(self.statusLayout)

        self.runbutton = QPushButton(self.START_BUTTON_TEXT)
        self.runbutton.clicked.connect(self._run)
        self.statusLayout.addWidget(self.runbutton)

        self.openbutton = QPushButton("Open")
        self.statusLayout.addWidget(self.openbutton)

        self.savebutton = QPushButton("Save")
        self.statusLayout.addWidget(self.savebutton)

        self.scripteditor = QTextEdit()
        # self.scripteditor.insertPlainText('import time;print("hi1");time.sleep(3);print("hi2")')
        # self.scripteditor.insertPlainText('print(mints.devices["Generic Sensor 1"].value)')
        
        self.layout.addWidget(self.scripteditor)

        self.filename = "script.py"
        self._load(self.filename)

        self.mints: MintsScriptAPI = mintsapi

    def _load(self, filename: str = None):
        if filename is None:
            self.log.error("Can't try to select file yet")
        if os.path.isfile(filename):
            with open(filename) as f:
                for line in f:
                    self.scripteditor.insertPlainText(line)
            self.log.info(f"Loaded file {filename}")
        else:
            self.log.error(f"Can not open file {filename} since it doesn't exist")

    def _done(self):
        self.running.clear()
        self.runbutton.setText(self.START_BUTTON_TEXT)
        self.log.info("Script done running")

    def _run(self):
        if self.running.isSet():
            self.stop()
        else:
            self.log.info("Starting script now")
            self.running.set()
            script = self.scripteditor.toPlainText()
            def runthread(script, doneSignal):
                log = logging.getLogger("script.exec")
                try:
                    exec(script, {
                        "print": log.info,
                        "mints": self.mints
                    })
                except Exception as e:
                    self.log.fatal(repr(e))
                    self.mints.abort()
                doneSignal.emit()

            self.runner = threading.Thread(target=runthread, args=(script, self.doneSignal))
            self.runner.start()
            self.runbutton.setText(self.STOP_BUTTON_TEXT)

    def scriptPrint(self, message):
        self.log.info(message)
        
    def stop(self):
        ''' Forcefully stop script execution. NOT YET IMPLEMENTED!!!!! '''
        self.log.error("Can't stop thread yet!")