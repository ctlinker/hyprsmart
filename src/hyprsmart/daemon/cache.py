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


def _sanitize_profile_visuals(vis: WindowVisuals) -> tuple[WindowVisuals, bool]:
    """
    Ensure class profile visuals maintain physically valid foreground/background contrast
    and repair entries previously corrupted by thumbnail blur or over-clamped highlights.
    """
    text_l = float(vis.text_l)
    bg_l = float(vis.bg_l)
    text_density = float(vis.text_density)
    bg_ratio = float(vis.bg_ratio)
    changed = False

    if bg_l < 0.35 and text_l < 0.38:
        text_l = round(max(text_l, min(0.48, bg_l + 0.42)), 4)
        changed = True
    elif bg_l < 0.35 and text_l > 0.62:
        text_l = round(min(text_l, 0.54), 4)
        changed = True
    elif bg_l >= 0.50 and text_l > 0.22:
        text_l = round(min(text_l, max(0.06, bg_l - 0.62)), 4)
        changed = True

    if changed:
        return (
            WindowVisuals(
                text_l=text_l,
                bg_l=round(bg_l, 4),
                text_density=round(text_density, 4),
                bg_ratio=round(bg_ratio, 4),
            ),
            True,
        )
    return vis, False


def load_class_profiles() -> dict[str, WindowVisuals]:
    """Load persistent class profiles from ~/.config/hyprsmart/profiles.json."""
    with CACHE_LOCK:
        if not PROFILES_FILE.exists():
            return CLASS_PROFILES
        needs_resave = False
        try:
            raw_data = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
            for cls_name, vals in raw_data.items():
                if isinstance(vals, dict):
                    vis = WindowVisuals(
                        text_l=float(vals.get("text_l", 0.5)),
                        bg_l=float(vals.get("bg_l", 0.05)),
                        text_density=float(vals.get("text_density", 0.1)),
                        bg_ratio=float(vals.get("bg_ratio", 0.8)),
                    )
                    sanitized, repaired = _sanitize_profile_visuals(vis)
                    CLASS_PROFILES[cls_name] = sanitized
                    if repaired:
                        needs_resave = True
        except Exception as e:
            print(f"[WARN] Failed to load class profiles from {PROFILES_FILE}: {e}")
        if needs_resave:
            save_class_profiles()
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


def update_class_profile(
    window_class: str,
    visuals: WindowVisuals,
    captured_alpha: float = 1.0,
) -> None:
    if not window_class:
        return
    sanitized_vis, _ = _sanitize_profile_visuals(visuals)
    with CACHE_LOCK:
        if window_class not in CLASS_PROFILES:
            CLASS_PROFILES[window_class] = sanitized_vis
        else:
            old = CLASS_PROFILES[window_class]
            # Confidence-weighted EMA: full 0.30 learning rate when opaque (alpha >= 0.95),
            # reduced learning rate when transparent to prevent wallpaper bleed drift.
            if captured_alpha >= 0.95:
                w_new = 0.30
                eff_bg_ratio = sanitized_vis.bg_ratio
            else:
                w_new = max(0.05, min(0.20, (captured_alpha - 0.25) * 0.25))
                # Prevent transparent captures from artificially eroding learned bg_ratio
                eff_bg_ratio = max(old.bg_ratio * 0.95, sanitized_vis.bg_ratio)

            w_old = 1.0 - w_new
            CLASS_PROFILES[window_class] = WindowVisuals(
                text_l=round(w_old * old.text_l + w_new * sanitized_vis.text_l, 4),
                bg_l=round(w_old * old.bg_l + w_new * sanitized_vis.bg_l, 4),
                text_density=round(w_old * old.text_density + w_new * sanitized_vis.text_density, 4),
                bg_ratio=round(w_old * old.bg_ratio + w_new * eff_bg_ratio, 4),
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
    captured_alpha: float | None = None,
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
        eff_alpha = captured_alpha if captured_alpha is not None else APPLIED_ALPHAS.get(win.address, last_alpha)
        WIN_CACHE[win.address] = WinEntry(
            visuals=vis,
            title=win.title,
            time_set=time.time(),
            last_alpha=last_alpha,
        )
        if win.window_class:
            update_class_profile(win.window_class, vis, captured_alpha=eff_alpha)


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