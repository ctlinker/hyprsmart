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
    last_alpha: float = 1.0
    last_backdrop_sig: tuple[float, float, float] | None = None
    last_geom: tuple[int, int, int, int] | None = None

    @property
    def text_l(self) -> float:
        return self.visuals.text_l

    @property
    def bg_l(self) -> float:
        return self.visuals.bg_l


WIN_CACHE: dict[str, WinEntry] = {}
CLASS_CACHE: dict[str, WindowVisuals] = {}
CACHE_LOCK = Lock()
MAX_AGE: float = 1800.0  # 30 minutes


def cache_get(win: Window) -> None | WinEntry:
    now = time.time()
    with CACHE_LOCK:
        e = WIN_CACHE.get(win.address)
        if e and e.title == win.title and (now - e.time_set < MAX_AGE):
            return e

        # If title changed or instance not found, fall back to learned class visuals
        if win.window_class and win.window_class in CLASS_CACHE:
            class_vis = CLASS_CACHE[win.window_class]
            # Return synthetic or updated entry using class visuals
            last_alpha = e.last_alpha if e else 1.0
            return WinEntry(
                visuals=class_vis,
                title=win.title,
                time_set=now,
                last_alpha=last_alpha,
            )

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
        existing = WIN_CACHE.get(win.address)
        last_alpha = existing.last_alpha if existing else 1.0
        WIN_CACHE[win.address] = WinEntry(
            visuals=vis,
            title=win.title,
            time_set=time.time(),
            last_alpha=last_alpha,
        )
        if win.window_class:
            CLASS_CACHE[win.window_class] = vis


def record_applied_state(
    address: str,
    alpha: float,
    backdrop_sig: tuple[float, float, float] | None = None,
    geom: tuple[int, int, int, int] | None = None,
) -> None:
    with CACHE_LOCK:
        entry = WIN_CACHE.get(address)
        if entry:
            entry.last_alpha = alpha
            entry.last_backdrop_sig = backdrop_sig
            entry.last_geom = geom


def get_applied_alpha(address: str) -> float:
    with CACHE_LOCK:
        entry = WIN_CACHE.get(address)
        if entry:
            return entry.last_alpha
    return 1.0


def cache_drop(address: str) -> None:
    with CACHE_LOCK:
        WIN_CACHE.pop(address, None)


def cache_clear() -> None:
    with CACHE_LOCK:
        WIN_CACHE.clear()
        CLASS_CACHE.clear()