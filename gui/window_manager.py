# gui/window_manager.py
from PyQt5.QtCore import QObject
from PyQt5.QtWidgets import QApplication

from .controller_window import ControllerWindow
from .scada_window import ScadaWindow


class DualWindowManager(QObject):
    """
    Dispatch hub:
    - Manages two windows and places each one full-screen on a separate display.
    - Also exposes compatibility APIs such as timeline / playback_time /
      change_test_requested / addDevice to match existing usage.
    """

    def __init__(self, parent=None, loghandler=None, autopoller=None, playback_mode=False, test_name=None):
        super().__init__(parent)

        self.controller = ControllerWindow(
            loghandler=loghandler,
            autopoller=autopoller,
            playback_mode=playback_mode,
            test_name=test_name,
            manager=self,
        )
        self.scada = ScadaWindow(
            playback_mode=playback_mode,
            test_name=test_name,
            manager=self,
        )

    # ---- Compatibility with existing main.py usage ----
    @property
    def timeline(self):
        return self.controller.timeline

    @property
    def playback_time(self):
        return self.controller.playback_time

    @playback_time.setter
    def playback_time(self, v):
        self.controller.playback_time = v

    @property
    def change_test_requested(self):
        return getattr(self.controller, "change_test_requested", False)

    def addDevice(self, *args, **kwargs):
        return self.controller.addDevice(*args, **kwargs)

    # ---- Show and close ----
    def show(self):
        screens = QApplication.screens()
        screens_sorted = sorted(screens, key=lambda s: s.geometry().x())

        if len(screens_sorted) >= 2:
            left = screens_sorted[0]
            right = screens_sorted[1]
            self._show_fullscreen_on_screen(self.controller, left)
            self._show_fullscreen_on_screen(self.scada, right)
        else:
            self._show_fullscreen_on_screen(self.controller, screens_sorted[0])
            self.scada.resize(1200, 800)
            self.scada.show()

    def close_all(self):
        # Close SCADA first, then the controller, to avoid duplicate triggers.
        try:
            self.scada.blockSignals(True)
            self.scada.close()
        except Exception:
            pass
        try:
            self.controller.blockSignals(True)
            self.controller.close()
        except Exception:
            pass

    def _show_fullscreen_on_screen(self, win, screen):
        geom = screen.geometry()
        win.setGeometry(geom)
        win.show()
        if win.windowHandle():
            win.windowHandle().setScreen(screen)
        win.showFullScreen()


# Key: export a callable window_manager so main.py does not need major changes.
def window_manager(*, loghandler=None, autopoller=None, playback_mode=False, test_name=None):
    return DualWindowManager(
        loghandler=loghandler,
        autopoller=autopoller,
        playback_mode=playback_mode,
        test_name=test_name,
    )