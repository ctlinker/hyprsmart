import time
from dataclasses import dataclass
from threading import Lock

from hyprsmart.opacity.win_col import WindowVisuals
from hyprsmart.primitive import Window


@dataclass
class WinEntry:
    visuals: WindowVisuals
    title: str
    time_set: float

    @property
    def text_l(self) -> float:
        return self.visuals.text_l

    @property
    def bg_l(self) -> float:
        return self.visuals.bg_l


WIN_CACHE: dict[str, WinEntry] = {}
CACHE_LOCK = Lock()
MAX_AGE = 30


def cache_get(win: Window) -> None | WinEntry:
    with CACHE_LOCK:
        e = WIN_CACHE.get(win.address)
    if e and e.title == win.title and time.time() - e.time_set < MAX_AGE:
        return e
    return None


def cache_put(
    win: Window,
    visuals: WindowVisuals | float,
    bg_l: float | None = None,
) -> None:
    if not isinstance(visuals, WindowVisuals):
        vis = WindowVisuals(
            text_l=float(visuals),
            bg_l=float(bg_l or 0.0),
            text_density=0.2,
            bg_ratio=0.8,
        )
    else:
        vis = visuals

    with CACHE_LOCK:
        WIN_CACHE[win.address] = WinEntry(
            visuals=vis,
            title=win.title,
            time_set=time.time(),
        )


def cache_drop(address: str) -> None:
    with CACHE_LOCK:
        WIN_CACHE.pop(address, None)


def cache_clear() -> None:
    with CACHE_LOCK:
        WIN_CACHE.clear()