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


import json
from pathlib import Path
from hyprsmart.config import CONFIG_DIR

PROFILES_FILE = CONFIG_DIR / "profiles.json"

WIN_CACHE: dict[str, WinEntry] = {}
APPLIED_ALPHAS: dict[str, float] = {}
CLASS_PROFILES: dict[str, WindowVisuals] = {}
# Alias for backward compatibility
CLASS_CACHE = CLASS_PROFILES
CACHE_LOCK = RLock()
MAX_AGE: float = 1800.0  # 30 minutes


def load_class_profiles() -> dict[str, WindowVisuals]:
    """Load persistent class profiles from ~/.config/hyprsmart/profiles.json."""
    with CACHE_LOCK:
        if not PROFILES_FILE.exists():
            return CLASS_PROFILES
        try:
            raw_data = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
            for cls_name, vals in raw_data.items():
                if isinstance(vals, dict):
                    CLASS_PROFILES[cls_name] = WindowVisuals(
                        text_l=float(vals.get("text_l", 0.5)),
                        bg_l=float(vals.get("bg_l", 0.05)),
                        text_density=float(vals.get("text_density", 0.1)),
                        bg_ratio=float(vals.get("bg_ratio", 0.8)),
                    )
        except Exception as e:
            print(f"[WARN] Failed to load class profiles from {PROFILES_FILE}: {e}")
        return CLASS_PROFILES


def save_class_profiles() -> None:
    """Save persistent class profiles to ~/.config/hyprsmart/profiles.json."""
    with CACHE_LOCK:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                cls_name: {
                    "text_l": vis.text_l,
                    "bg_l": vis.bg_l,
                    "text_density": vis.text_density,
                    "bg_ratio": vis.bg_ratio,
                }
                for cls_name, vis in CLASS_PROFILES.items()
            }
            tmp_file = PROFILES_FILE.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_file.replace(PROFILES_FILE)
        except Exception as e:
            print(f"[WARN] Failed to save class profiles to {PROFILES_FILE}: {e}")


# Initialize profiles on module load
load_class_profiles()


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
        save_class_profiles()


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