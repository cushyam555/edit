from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QPushButton


class Piano(QWidget):
    pressed = Signal(int)
    released = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(125)
        self.keys = {}
        self.white = []
        self.black = []
        whites = 0
        for note in range(48, 73):
            sharp = note % 12 in (1, 3, 6, 8, 10)
            button = QPushButton(
                (
                    ""
                    if sharp
                    else f"{['C','D','E','F','G','A','B'][[0,2,4,5,7,9,11].index(note%12)]}{note//12-1}"
                ),
                self,
            )
            button.setStyleSheet(
                "QPushButton{background:#253339;color:white;border:1px solid #172925;border-radius:0px 0px 4px 4px} QPushButton:pressed{background:#008c80}"
                if sharp
                else "QPushButton{background:white;color:#536962;border:1px solid #9aaba6;border-radius:0px 0px 4px 4px;padding-top:65px} QPushButton:pressed{background:#bfe8df}"
            )
            button.pressed.connect(lambda n=note: self.pressed.emit(n))
            button.released.connect(lambda n=note: self.released.emit(n))
            self.keys[note] = button
            if sharp:
                self.black.append((button, whites))
            else:
                self.white.append(button)
                whites += 1

    def resizeEvent(self, event):
        width = self.width() / len(self.white)
        for i, key in enumerate(self.white):
            key.setGeometry(
                round(i * width),
                0,
                round((i + 1) * width) - round(i * width),
                self.height(),
            )
        for key, pos in self.black:
            key.setGeometry(
                round(pos * width - width * 0.31),
                0,
                round(width * 0.62),
                round(self.height() * 0.62),
            )
            key.raise_()
        super().resizeEvent(event)
