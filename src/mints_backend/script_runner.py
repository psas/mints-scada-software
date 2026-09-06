import logging
import shlex
import shutil
import sys

from PySide6.QtCore import QProcess

logger = logging.getLogger(__name__)


class ScriptRunner:
    def __init__(self):
        exec: str | None = shutil.which(sys.executable)
        if exec is None:
            raise OSError("Unable to determine path to Python3 executable")
        self.py_path = exec
        self.process = QProcess()
        self.process.readyReadStandardOutput.connect(self._on_output)
        self.process.finished.connect(self._on_finished)

    def run(self, script: str, path: str) -> None:
        if not script:
            logger.info("No script to run")
            return
        logger.info(f"Running {path}")
        args = shlex.split(f"-c '{script}'")
        self.process.start(self.py_path, args)

    def stop(self) -> None:
        if self.process.state() == QProcess.NotRunning:
            logger.error("No process running to stop")
            return
        self.process.kill()
        logger.info("Stopped script execution")

    def _on_output(self):
        outbytes = self.process.readAllStandardOutput()
        raw = outbytes.data()
        lines = raw.decode()
        out = "Script output:\n"
        for line in lines:
            out += line
        out = out.removesuffix("\n")
        logger.info(out)

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus):
        logger.info(f"Script exited with code {exit_code} ({exit_status.name})")
