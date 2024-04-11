import math
from typing import Tuple
from PyQt5.QtGui import QValidator
from PyQt5.QtWidgets import QDoubleSpinBox
import re

class DecadeSpinBox(QDoubleSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._steps = [1, 2, 5]
        self.__bigPre = "kMgt"
        self.__smallPre = "munpfa"

    def stepBy(self, count):
        omag = math.floor(math.log10(self.value())) if self.value() != 0 else 0
        factor = 10 ** omag
        if count > 0:
            for step in self._steps:
                big = (step * factor) > self.value()
                if big:
                    self.setValue(step * factor)
                    return
            self.setValue(self._steps[0] * (10 ** (omag+1)))
        else:
            for step in self._steps[::-1]:
                small = (step * factor) < self.value()
                if small:
                    self.setValue(step * factor)
                    return
            self.setValue(self._steps[-1] * (10 ** (omag-1)))

    def textFromValue(self, value: float) -> str:
        bigPre = self.__bigPre
        smallPre = self.__smallPre
        if value >= 1e3:
            value /= 1e3
            for i in range(len(bigPre)-1):
                if value >= 1e3:
                    value /= 1e3
                    bigPre = bigPre[1:]
            return f"{value:.3g}{bigPre [0]}"
        elif value < 1:
            value *= 1e3
            for i in range(len(smallPre)-1):
                if value < 1:
                    value *= 1e3
                    smallPre = smallPre[1:]
            return f"{value:.3g}{smallPre[0]}"
        return f"{value:.3g}"

    def valueFromText(self, text: str) -> float:
        factor = 1
        if text.endswith(self.suffix()):
            text = text[:-len(self.suffix())]
        if text[-1] in self.__smallPre:
            for i in range(len(self.__smallPre)):
                factor /= 1e3
                if self.__smallPre[i] == text[-1]:
                    break
            text = text[:-1]
        if text[-1] in self.__bigPre:
            for i in range(len(self.__bigPre)):
                factor *= 1e3
                if self.__bigPre[i] == text[-1]:
                    break
            text = text[:-1]
        num = float(text) * factor
        exp = math.log10(num)
        siz = math.trunc(exp)
        sig = round(10 ** (exp - siz), 2)
        num = sig * 10 ** siz
        return num
    
    def validate(self, input: str, pos: int) -> Tuple[QValidator.State, str, int]:
        regex = "^[0-9.]+[" + self.__smallPre + self.__bigPre + "]?(?:" + self.suffix().replace("/", "\\/") + ")?$"
        if len(input) > 0:
            res = re.search(regex, input)
            if res is not None:
                return (QValidator.State.Acceptable, input, pos)
            else:
                return (QValidator.State.Invalid, input, pos)
        return (QValidator.State.Acceptable, "", 0)