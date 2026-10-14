import time
from dataclasses import dataclass
from threading import RLock

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
APPLIED_ALPHAS: dict[str, float] = {}
CLASS_PROFILES: dict[str, WindowVisuals] = {}
# Alias for backward compatibility
CLASS_CACHE = CLASS_PROFILES
CACHE_LOCK = RLock()
MAX_AGE: float = 1800.0  # 30 minutes


def get_class_profile(window_class: str) -> WindowVisuals | None:
    with CACHE_LOCK:
        return CLASS_PROFILES.get(window_class)


def update_class_profile(window_class: str, visuals: WindowVisuals) -> None:
    if not window_class:
        return
    with CACHE_LOCK:
        if window_class not in CLASS_PROFILES:
            CLASS_PROFILES[window_class] = visuals
        else:
            old = CLASS_PROFILES[window_class]
            # Exponential Moving Average (70% prior, 30% new)
            CLASS_PROFILES[window_class] = WindowVisuals(
                text_l=round(0.7 * old.text_l + 0.3 * visuals.text_l, 4),
                bg_l=round(0.7 * old.bg_l + 0.3 * visuals.bg_l, 4),
                text_density=round(0.7 * old.text_density + 0.3 * visuals.text_density, 4),
                bg_ratio=round(0.7 * old.bg_ratio + 0.3 * visuals.bg_ratio, 4),
            )


def cache_get(win: Window) -> None | WinEntry:
    now = time.time()
    with CACHE_LOCK:
        e = WIN_CACHE.get(win.address)
        if e and e.title == win.title and (now - e.time_set < MAX_AGE):
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
        existing = WIN_CACHE.get(win.address)
        last_alpha = existing.last_alpha if existing else 1.0
        WIN_CACHE[win.address] = WinEntry(
            visuals=vis,
            title=win.title,
            time_set=time.time(),
            last_alpha=last_alpha,
        )
        if win.window_class:
            update_class_profile(win.window_class, vis)


def record_applied_state(
    address: str,
    alpha: float,
    backdrop_sig: tuple[float, float, float] | None = None,
    geom: tuple[int, int, int, int] | None = None,
) -> None:
    with CACHE_LOCK:
        APPLIED_ALPHAS[address] = alpha
        entry = WIN_CACHE.get(address)
        if entry:
            entry.last_alpha = alpha
            entry.last_backdrop_sig = backdrop_sig
            entry.last_geom = geom


def get_applied_alpha(address: str) -> float:
    with CACHE_LOCK:
        if address in APPLIED_ALPHAS:
            return APPLIED_ALPHAS[address]
        entry = WIN_CACHE.get(address)
        if entry:
            return entry.last_alpha
    return 1.0


def cache_drop(address: str) -> None:
    with CACHE_LOCK:
        WIN_CACHE.pop(address, None)
        APPLIED_ALPHAS.pop(address, None)


def cache_clear() -> None:
    with CACHE_LOCK:
        WIN_CACHE.clear()
        APPLIED_ALPHAS.clear()
        CLASS_CACHE.clear()