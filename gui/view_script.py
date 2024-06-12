from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QPlainTextEdit, QCheckBox, QMessageBox
from PyQt5.QtCore import Qt, pyqtSignal
import logging
import threading
from gui import MintsScriptAPI
import os
import ctypes

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
    _THREAD_KILL_DELAY = 0.01
    ''' The delay between asking the thread to stop and brutally murdering it '''

    START_BUTTON_TEXT = "Run Script"
    STOP_BUTTON_TEXT = "Stop Script"
    STOPPING_BUTTON_TEXT = "Stopping script ..."

    # This has to go here, not in the constructor. Not sure why, but this works.
    doneSignal = pyqtSignal()
    ''' Signal to trigger when the script is done '''
    stoppedSignal = pyqtSignal()
    ''' Signal to trigger when the script is stopped '''

    def __init__(self, mintsapi):
        super().__init__()
        self.log = logging.getLogger("script")

        self.running = threading.Event()
        ''' Event to trigger when the script starts/stops '''

        self.mints: MintsScriptAPI = mintsapi
        ''' The minTS API scripts can use '''

        # Set up signals
        self.doneSignal.connect(self._done)
        self.stoppedSignal.connect(self._setStoppingText)

        # Main Layout
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.layout.setAlignment(Qt.AlignTop)

        self.controlLayout = QHBoxLayout()
        ''' Layout at the top for control buttons '''
        self.layout.addLayout(self.controlLayout)

        # self.scripteditor = QTextEdit()
        self.scripteditor = QPlainTextEdit()
        ''' Main editor window for the script '''
        self.layout.addWidget(self.scripteditor)

        # Run Controls
        self.runbutton = QPushButton(self.START_BUTTON_TEXT)
        self.runbutton.clicked.connect(self._run)
        self.controlLayout.addWidget(self.runbutton)

        # Space things out
        self.controlLayout.addStretch()

        # Editor Controls
        self.openbutton = QPushButton("Open")
        self.openbutton.clicked.connect(self._load)
        self.controlLayout.addWidget(self.openbutton)

        self.savebutton = QPushButton("Save")
        self.savebutton.clicked.connect(self._save)
        self.controlLayout.addWidget(self.savebutton)

        # Lock editor checkbox. If it is partially checked, that is unlocked normally but locked now since the script is running
        self.lockcheck = QCheckBox("Lock editor")
        self.lockcheck.toggled.connect(self._updateLock)
        self.lockcheck.setChecked(True)
        self.controlLayout.addWidget(self.lockcheck)

        # Load the default script
        self.filename = "script.py"
        self._load(self.filename)

    def _load(self, filename: str = None):
        ''' Loads a script file, either the currently selected one, or (in future) let the user select the file '''
        # Prepare the filename
        if filename is None:
            self.log.error("Can't try to select file yet")
        self.filename = filename
        # Load the file and put it in the editor
        if os.path.isfile(self.filename):
            with open(self.filename) as f:
                for line in f:
                    self.scripteditor.insertPlainText(line)
            self.log.info(f"Loaded file {self.filename}")
        else:
            msg = f"Can not open file {self.filename} since it doesn't exist"
            self.log.error(msg)
            # self._alerter(msg)

    def _save(self):
        self.log.info("Saving now")
        with open(self.filename, "w") as f:
            f.write(self.scripteditor.toPlainText())
        msg = f"Saved file {self.filename}"
        self.log.info(msg)
        QMessageBox.information(self.parent(), "File saved", msg)

    def _updateLock(self):
        self.log.info("Checkbox state changed")
        if self.lockcheck.isChecked():
            self._lock()
            self.log.info("Script editor locked")
        else:
            ynb = QMessageBox(self.parent())
            yes = QMessageBox.StandardButton.Yes
            if ynb.question(self.parent(), "Unlock Verification", "Do you want to unlock the editor?", yes |  QMessageBox.StandardButton.No) == yes:
                self.log.info("Script editor unlocked")
                if not self.running.isSet():
                    self._unlock()
            else:
                self.lockcheck.setChecked(True)
                self._lock()

    def _lock(self):
        # Disable file buttons
        self.openbutton.setEnabled(False)
        self.savebutton.setEnabled(False)
        # Lock the editor
        self.scripteditor.setReadOnly(True)

    def _unlock(self, force: bool = False):
        ''' Unlocks the editor but only if the lock checkbox is unchecked '''
        if not self.lockcheck.checkState() == Qt.CheckState.Checked or force:
            # Enable file buttons
            self.openbutton.setEnabled(True)
            self.savebutton.setEnabled(True)
            # Unlock the editor
            self.scripteditor.setReadOnly(False)
            self.lockcheck.blockSignals(True)       # Don't call the _updateLock method this time
            self.lockcheck.setChecked(False)
            self.lockcheck.blockSignals(False)
        # Uncheck the checkbox
        self.lockcheck.setEnabled(True)
        self.lockcheck.setTristate(False)
    
    def _setStoppingText(self):
        self.runbutton.setText(self.STOPPING_BUTTON_TEXT)

    def _done(self):
        self.runner = None
        self.runbutton.setText(self.START_BUTTON_TEXT)
        self._unlock()
        self.log.info("Script done running")

    def _run(self):
        if self.running.isSet():
            self.stop()
        else:
            self.log.info("Starting script now")
            self.running.set()
            self._waiter = threading.Event()
            script = self.scripteditor.toPlainText()
            def runthread(script, doneSignal):
                try:
                    # Internal variables for the script
                    log = logging.getLogger("script.exec")
                    def wait(time: float):
                        self._waiter.wait(time)
                    # Actually run the script
                    exec(script, {
                        "print": log.info,
                        "mints": self.mints,
                        "abort": self.mints.abort,
                        "exit": None,
                        "wait": wait
                    })
                except Exception as e:
                    # If something goes wrong, trigger an abort
                    self.log.fatal("An exception occurred in the script. Aborting now.")
                    self.log.fatal(repr(e))
                    self.mints.abort()
                except PleaseStopNowException:
                    # If we're asked nicely to stop, do so
                    self.log.info("Script received stop request")
                self.running.clear()
                doneSignal.emit()

            self.runner = threading.Thread(target=runthread, args=(script, self.doneSignal))
            self.runner.start()
            self._lock()
            self.runbutton.setText(self.STOP_BUTTON_TEXT)
            self.lockcheck.setTristate(True)
            # Mark things as locked if they were unlocked before
            self.lockcheck.setEnabled(False)
            if not self.lockcheck.isChecked():
                self.lockcheck.setCheckState(Qt.CheckState.PartiallyChecked)


    def scriptPrint(self, message):
        self.log.info(message)
        
    def stop(self):
        ''' Ask the script to stop execution. This does NOT force the script to stop '''
        if self.runner is not None:
            self.log.error("Asking script to stop")
            thread_id = self.runner.ident
            exception = PleaseStopNowException
            # Based on https://stackoverflow.com/questions/36484151/throw-an-exception-into-another-thread
            ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread_id), ctypes.py_object(exception))
            # ref: http://docs.python.org/c-api/init.html#PyThreadState_SetAsyncExc
            if ret == 0:
                raise ValueError("Invalid thread ID")
            elif ret > 1:
                # Huh? Why would we notify more than one threads?
                # Because we punch a hole into C level interpreter.
                # So it is better to clean up the mess.
                ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, 0)
                raise SystemError("PyThreadState_SetAsyncExc failed")
            else:
                self.stoppedSignal.emit()
            # Stop any delays
            self._waiter.set()
            # Give the script a few ms to stop before we forcefully kill it.
            self.runner.join(self._THREAD_KILL_DELAY)
            if self.running.isSet():
                # If it's not done yet, ask the user to press Estop
                self.log.warn("Script didn't die in 10ms, this is bad!")
                QMessageBox.critical(self.parent(), "Script did not stop", f"The script didn't stop in {self._THREAD_KILL_DELAY*1000:.0f}ms\nPRESS E-STOP NOW!")
            else:
                self.log.info("Script stopped in time")

class PleaseStopNowException(BaseException):
    def __init__(self):
        super().__init__()