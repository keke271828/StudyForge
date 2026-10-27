"""Experimental A sampling: retain changes and merge near-identical adjacent views."""
from __future__ import annotations

from PIL import Image
import numpy as np


class KeyframeSelector:
    def __init__(self):
        self.previous = None
        self.last_time = None

    def retain(self, path, timestamp, *, final=False):
        with Image.open(path) as source:
            current = np.asarray(source.convert('L').resize((640, 360)), dtype=np.int16)
        if self.previous is None or self.last_time is None or final or timestamp is None:
            retain = True
        else:
            delta = np.abs(current - self.previous)
            # A local change (a newly written symbol) matters even if the mean
            # across the whole board is tiny. Compare against the last retained
            # frame, so incremental changes cannot vanish through chaining.
            tiles = delta.reshape(12, 30, 20, 32).mean(axis=(1, 3))
            retain = (float(delta.mean()) > .30 or float(tiles.max()) > .65
                      or timestamp - self.last_time >= 60)
        if retain:
            self.previous, self.last_time = current, timestamp
        return retain
