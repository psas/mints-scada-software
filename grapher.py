import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
import matplotlib.pyplot as plt

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        # Create layout
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # Initialize plot data
        self.x = [0]
        self.y = [0]

        # Create Matplotlib figure and plot
        self.fig, self.ax = plt.subplots()
        self.line, = self.ax.plot(self.x, self.y)
        self.ax.set_xlim(0, 2)
        self.ax.set_ylim(0, 2)

        # Create Matplotlib widget for PyQt
        self.canvas = FigureCanvasQTAgg(self.fig)

        # Add elements to layout
        self.layout.addWidget(self.canvas)

        # Create a timer to simulate data arrival
        self.timer = self.startTimer(1000)  # Update every 1 second

    def timerEvent(self, event):
        # Simulate new data arrival
        self.x.append(self.x[-1] + 0.1)
        self.y.append(self.y[-1] + 0.2)

        # Update plot data
        self.line.set_xdata(self.x)
        self.line.set_ydata(self.y)

        # Redraw the plot
        self.ax.draw_artist(self.line)
        self.canvas.draw_idle()

    def startTimer(self, interval):
        super().startTimer(interval)
        return True


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())