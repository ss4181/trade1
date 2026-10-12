"""Bounded retry of Windows sharing locks without losing atomic replacement."""
from pathlib import Path
import time


def replace_state(source: Path, target: Path) -> None:
    for attempt in range(6):
        try:
            source.replace(target)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                raise
            time.sleep(.02 * 2**attempt)
