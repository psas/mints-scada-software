"""gui/decadespinbox.py

Engineering-style spin box with decade-based stepping and SI-prefix parsing.
"""

import math
import re
from typing import Tuple

from PyQt5.QtGui import QValidator
from PyQt5.QtWidgets import QDoubleSpinBox


class DecadeSpinBox(QDoubleSpinBox):
    """Spin box that steps through 1-2-5 values across powers of ten.

    The widget formats values with a compact SI-style prefix, parses the same
    prefix form back into floats, and validates user input against that
    decimal-plus-prefix representation.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the spin box with decade stepping and prefix tables.

        Args:
            *args: Positional arguments forwarded to ``QDoubleSpinBox``.
            **kwargs: Keyword arguments forwarded to ``QDoubleSpinBox``.
        """
        super().__init__(*args, **kwargs)
        self._steps = [1, 2, 5]
        self.__bigPre = "kMgt"
        self.__smallPre = "munpfa"
        self.setDecimals(18)

    def stepBy(self, count):
        """Advance the value along the 1-2-5 engineering sequence.

        Positive step counts move to the next larger value in the current
        decade or the first step in the next decade. Non-positive counts move
        to the next smaller value in the current decade or the last step in the
        previous decade.

        Args:
            count: Step direction supplied by Qt.
        """
        omag = math.floor(math.log10(self.value())) if self.value() != 0 else 0
        factor = 10**omag
        if count > 0:
            for step in self._steps:
                big = (step * factor) > self.value()
                if big:
                    self.setValue(step * factor)
                    return
            self.setValue(self._steps[0] * (10 ** (omag + 1)))
        else:
            for step in self._steps[::-1]:
                small = (step * factor) < self.value()
                if small:
                    self.setValue(step * factor)
                    return
            self.setValue(self._steps[-1] * (10 ** (omag - 1)))

    def textFromValue(self, value: float) -> str:
        """Format a numeric value with a compact SI-style prefix.

        Values at or above ``1e3`` are scaled with the larger prefix table.
        Values below ``1`` are scaled with the smaller prefix table. Values in
        between are rendered without a prefix.

        Args:
            value: Numeric value to display.

        Returns:
            The display string used by the spin box.
        """
        bigPre = self.__bigPre
        smallPre = self.__smallPre
        if value >= 1e3:
            value /= 1e3
            for i in range(len(bigPre) - 1):
                if value >= 1e3:
                    value /= 1e3
                    bigPre = bigPre[1:]
            return f"{value:.3g}{bigPre[0]}"
        elif value < 1:
            value *= 1e3
            for i in range(len(smallPre) - 1):
                if value < 1:
                    value *= 1e3
                    smallPre = smallPre[1:]
            return f"{value:.3g}{smallPre[0]}"
        return f"{value:.3g}"

    def valueFromText(self, text: str) -> float:
        """Parse a display string with an optional SI-style prefix.

        The parser removes the configured suffix when present, applies the
        matching large or small prefix scale, and normalizes the parsed number
        before returning it.

        Args:
            text: User-entered text to parse.

        Returns:
            The numeric value represented by ``text``.
        """
        factor = 1
        if text.endswith(self.suffix()):
            text = text[: -len(self.suffix())]
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
        if num == 0:
            return num
        exp = math.log10(num)
        siz = math.trunc(exp)
        sig = round(10 ** (exp - siz), 2)
        num = sig * 10**siz
        return num

    def validate(self, input: str, pos: int) -> Tuple[QValidator.State, str, int]:
        """Validate decimal input with an optional SI prefix and widget suffix.

        The accepted format is a plain decimal number, followed by at most one
        prefix character from the configured large or small prefix tables, and
        then the widget suffix if one is configured.

        Args:
            input: Current editor text.
            pos: Current cursor position.

        Returns:
            The Qt validator state tuple for the supplied text.
        """
        regex = (
            "^[0-9.]+["
            + self.__smallPre
            + self.__bigPre
            + "]?(?:"
            + self.suffix().replace("/", "\\/")
            + ")?$"
        )
        if len(input) > 0:
            res = re.search(regex, input)
            if res is not None:
                return (QValidator.State.Acceptable, input, pos)
            else:
                return (QValidator.State.Invalid, input, pos)
        return (QValidator.State.Acceptable, "", 0)
