# scada_window.py
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt
import qdarkstyle


class ScadaWindow(QMainWindow):
    def __init__(self, playback_mode=False, test_name=None, manager=None):
        super().__init__()
        self.manager = manager
        self.playback_mode = playback_mode
        self.test_name = test_name

        self.setWindowTitle("minTS SCADA - Right Screen")
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt5"))

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        diagram = QFrame()
        diagram.setFrameShape(QFrame.StyledPanel)
        diagram.setStyleSheet("QFrame{background:#111; border:1px solid #444; border-radius:10px;}")
        dlay = QVBoxLayout(diagram)
        dlay.setContentsMargins(12, 12, 12, 12)

        lab = QLabel("SCADA diagram placeholder\n(Replace with a Draw.io / QGraphicsView widget)")
        lab.setAlignment(Qt.AlignCenter)
        lab.setStyleSheet("color:#bbb; font-size:16px;")

        dlay.addStretch()
        dlay.addWidget(lab)
        dlay.addStretch()
        layout.addWidget(diagram, 1)

        btn_col = QFrame()
        btn_col.setFixedWidth(220)
        btn_col.setStyleSheet("QFrame{background:#2b2b2b; border:1px solid #444; border-radius:10px;}")
        blay = QVBoxLayout(btn_col)
        blay.setContentsMargins(16, 16, 16, 16)
        blay.setSpacing(14)

        for _ in range(4):
            b = QPushButton("Button")
            b.setMinimumHeight(72)
            b.setStyleSheet(
                """
                QPushButton{
                    background:#8e24aa; color:white; border:none;
                    border-radius:10px; font-size:16px; font-weight:800;
                }
                QPushButton:hover{ background:#7b1fa2; }
                QPushButton:pressed{ background:#6a1b9a; }
            """
            )
            blay.addWidget(b)

        blay.addStretch()
        layout.addWidget(btn_col, 0)

    def closeEvent(self, event):
        if self.manager:
            self.manager.close_all()
        event.accept()