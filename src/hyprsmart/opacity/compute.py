from .backdrop import Backdrop
from .win_col import WindowVisuals
import numpy as np


def _ratio(a: float, b: float) -> float:
    """Calculate WCAG 2.x relative contrast ratio between two relative luminance values."""
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def decide_opacity(
    win_vis: WindowVisuals | float | None = None,
    bg_l_or_backdrop: float | Backdrop | None = None,
    b: Backdrop | None = None,
    target: float = 4.5,
    floor: float = 0.5,
    *,
    text_l: float | None = None,
    bg_l: float | None = None,
) -> float:
    """
    Decide the optimal window opacity based on visual density, wallpaper clutter,
    and adaptive WCAG contrast ratio.

    Supports both:
    1. decide_opacity(win_vis: WindowVisuals, b: Backdrop, target=4.5, floor=0.5)
    2. decide_opacity(text_l: float, bg_l: float, b: Backdrop, target=4.5, floor=0.5)
    """
    if text_l is not None:
        win_vis = text_l
    if bg_l is not None:
        bg_l_or_backdrop = bg_l

    if isinstance(win_vis, WindowVisuals):
        vis = win_vis
        if isinstance(bg_l_or_backdrop, Backdrop):
            backdrop = bg_l_or_backdrop
        elif b is not None:
            backdrop = b
        else:
            raise ValueError("Backdrop must be provided to decide_opacity")
        # Handle kwargs or shifted positional args
        if isinstance(b, (int, float)):
            target = float(b)
    else:
        text_val = float(win_vis if win_vis is not None else 0.95)
        bg_val = float(bg_l_or_backdrop if bg_l_or_backdrop is not None else 0.05)
        vis = WindowVisuals(text_l=text_val, bg_l=bg_val, text_density=0.2, bg_ratio=0.8)
        if b is None or not isinstance(b, Backdrop):
            raise ValueError("Backdrop must be provided as 3rd argument for legacy decide_opacity signature")
        backdrop = b

    # 1. Adapt target contrast based on background high-frequency edge energy
    # Calm/blurred wallpaper (edge_energy < 0.04) allows relaxing target down to 3.0 (WCAG AA large text)
    # Busy/patterned wallpaper (edge_energy >= 0.12) requires strict full target (4.5)
    clutter_factor = max(0.0, min(1.0, (0.12 - backdrop.edge_energy) / 0.12))
    effective_target = max(3.0, target - clutter_factor * 1.5)

    # 2. Relax slightly further for code editors / terminals with sparse text
    if vis.bg_ratio >= 0.70 and vis.text_density <= 0.15:
        effective_target = max(2.8, effective_target - 0.2)

    # 3. Choose backdrop sample points:
    # If the background has low high-frequency clutter and window has strong background dominance,
    # use trimmed percentiles (p15, p85) to avoid isolated specular noise locking the opacity.
    if backdrop.edge_energy < 0.08 and vis.bg_ratio >= 0.65:
        samples = (backdrop.p15, backdrop.p85)
    else:
        samples = (backdrop.p5, backdrop.p95)

    # 4. Search for the lowest opacity 'a' in [floor, 1.0] that satisfies effective contrast
    for a in np.arange(floor, 1.001, 0.05):
        worst = min(
            _ratio(vis.text_l, a * vis.bg_l + (1.0 - a) * x)
            for x in samples
        )
        if worst >= effective_target:
            return float(round(a, 2))

    return 1.0
