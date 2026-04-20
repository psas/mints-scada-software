"""gui/window_manager.py

Manage the controller and SCADA top-level windows.

This module provides the two-window GUI coordinator used by legacy startup
paths. It owns the paired controller and SCADA windows, forwards a small set
of compatibility attributes used by older callers, and places the windows on
available displays.
"""

from PyQt5.QtCore import QObject
from PyQt5.QtWidgets import QApplication

from .controller_window import ControllerWindow
from .scada_window import ScadaWindow


class WindowManager(QObject):
    """Coordinate the controller and SCADA windows for a session.

    The manager creates one controller window and one SCADA window, exposes a
    few legacy compatibility attributes used by older startup code, and shows
    the two windows on separate screens when multiple displays are available.
    """

    def __init__(
        self,
        parent=None,
        loghandler=None,
        autopoller=None,
        playback_mode=False,
        test_name=None,
    ):
        """Initialize the paired session windows.

        Args:
            parent: Optional Qt parent object.
            loghandler: Optional log handler forwarded to the controller window.
            autopoller: Optional live telemetry poller forwarded to the
                controller window.
            playback_mode: Whether the session is running in playback mode.
            test_name: Optional test/run label forwarded to both windows.
        """
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
        """Return the controller timeline object used by legacy callers.

        Returns:
            The controller window's timeline attribute.
        """
        return self.controller.timeline

    @property
    def playback_time(self):
        """Return the controller playback time value.

        Returns:
            The current playback time maintained by the controller window.
        """
        return self.controller.playback_time

    @playback_time.setter
    def playback_time(self, v):
        """Update the controller playback time value.

        Args:
            v: Playback time value to forward to the controller window.
        """
        self.controller.playback_time = v

    @property
    def change_test_requested(self):
        """Return whether the controller requested a test change.

        Returns:
            The controller's ``change_test_requested`` flag when present, or
            False when the controller does not expose that attribute.
        """
        return getattr(self.controller, "change_test_requested", False)

    def addDevice(self, *args, **kwargs):
        """Forward device registration to the controller window.

        Args:
            *args: Positional arguments accepted by
                ``ControllerWindow.addDevice``.
            **kwargs: Keyword arguments accepted by
                ``ControllerWindow.addDevice``.

        Returns:
            The value returned by ``ControllerWindow.addDevice``.
        """
        return self.controller.addDevice(*args, **kwargs)

    # ---- Show and close ----
    def show(self):
        """Show the managed windows on the available displays.

        When at least two screens are available, the controller is placed on
        the leftmost screen and the SCADA window is placed on the next screen.
        On a single-screen system, the controller is shown fullscreen and the
        SCADA window is shown separately at a fixed size.
        """
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
        """Close both managed windows without propagating duplicate signals.

        The SCADA window is closed first, followed by the controller window.
        Signal blocking is used during shutdown to reduce duplicate close-side
        triggers from the paired windows.
        """
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
        """Place a window on a specific screen and show it fullscreen.

        Args:
            win: Top-level Qt window to place.
            screen: Target Qt screen object that provides the destination
                geometry.
        """
        geom = screen.geometry()
        win.setGeometry(geom)
        win.show()
        if win.windowHandle():
            win.windowHandle().setScreen(screen)
        win.showFullScreen()


# Key: export a callable window_manager so main.py does not need major changes.
def window_manager(
    *, loghandler=None, autopoller=None, playback_mode=False, test_name=None
):
    """Create the legacy-compatible window manager wrapper.

    Args:
        loghandler: Optional log handler forwarded to ``WindowManager``.
        autopoller: Optional autopoller forwarded to ``WindowManager``.
        playback_mode: Whether the session is running in playback mode.
        test_name: Optional test/run label forwarded to ``WindowManager``.

    Returns:
        A newly constructed ``WindowManager`` instance.
    """
    return WindowManager(
        loghandler=loghandler,
        autopoller=autopoller,
        playback_mode=playback_mode,
        test_name=test_name,
    )
