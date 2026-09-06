import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ScriptRunner:
    def try_run(self, path: Path) -> None:
        if not path:
            return
        logger.info("Trying to run %s", str(path))

    def stop(self):
        logger.info("Stopping script execution")
