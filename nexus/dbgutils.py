# nexus/dbgutils.py

"""Debugging helpers for formatting Python call stacks."""

import inspect


def getStackTrace():
    """Build a readable call stack string with shared path prefixes trimmed.

    The formatted output walks the current stack from oldest frame to newest
    frame and removes the longest common leading path prefix so each frame is
    shorter and easier to scan in logs.

    Returns:
        A multiline string beginning with ``"Call stack:"`` followed by one
        line per stack frame.
    """
    stack = inspect.stack()
    str = "Call stack:\n"
    lines = []
    parts = []
    for frame in stack[::-1]:
        fpts = f"{frame.filename}:{frame.lineno}".split("/")
        lines.append(fpts)
        for i in range(len(fpts)):
            if i == len(parts):
                parts.append([])
            if fpts[i] not in parts[i]:
                parts[i].append(fpts[i])
    start = 0
    for i in range(len(parts)):
        if len(parts[i]) > 1:
            start = i
            break
    for line in lines:
        str += f"\t{'/'.join(line[start:])}\n"
    return str
