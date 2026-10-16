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

    # 1. Adapt target contrast based on background high-frequency edge energy:
    #    Calm backdrops allow a slight relaxation (-0.20 max), whereas high-edge clutter
    #    increases the required contrast ratio (+1.0 max).
    clutter_adj = max(-0.20, min(1.0, (backdrop.edge_energy - 0.020) * 8.0))

    # 2. Smoothly relax target contrast for code editors / terminals with dominant background and sparse text
    bg_weight = max(0.0, min(1.0, (vis.bg_ratio - 0.50) / 0.25))
    sparse_weight = max(0.0, min(1.0, (0.18 - vis.text_density) / 0.12))
    sparse_relax = 0.30 * bg_weight * sparse_weight
    effective_target = max(2.8, target + clutter_adj - sparse_relax)

    # 3. Smoothly interpolate backdrop sample points between trimmed (p15, p85) and strict (p5, p95)
    edge_calm = max(0.0, min(1.0, (0.10 - backdrop.edge_energy) / 0.04))
    bg_dom = max(0.0, min(1.0, (vis.bg_ratio - 0.45) / 0.20))
    w_trim = edge_calm * bg_dom

    sample_low = w_trim * backdrop.p15 + (1.0 - w_trim) * backdrop.p5
    sample_high = w_trim * backdrop.p85 + (1.0 - w_trim) * backdrop.p95
    samples = (sample_low, sample_high)

    # 4. Calibrate foreground glyph luminance to prevent 4x thumbnail downscale blur or
    #    isolated pure-white highlights from compressing the solver's dynamic range.
    if vis.bg_l < 0.5:
        cal_text_l = min(0.60, max(vis.bg_l + 0.42, 0.48, 0.45 * vis.text_l + 0.55 * 0.52))
        raw_bleed = 0.35 * backdrop.median + 0.65 * sample_high
        # Wayland/Hyprland composites window alpha in gamma-encoded sRGB space (L^0.58),
        # and wallpaper variance (std) + spatial edges mask glyph strokes.
        disturb_l = min(
            1.0,
            (max(0.0, raw_bleed) ** 0.58)
            + 0.45 * backdrop.std
            + 1.10 * backdrop.edge_energy,
        )
        worst_l = min(1.0, (max(0.0, backdrop.p95) ** 0.58) + 0.50 * backdrop.std)
    else:
        cal_text_l = max(0.01, min(vis.bg_l - 0.45, 0.05, 0.45 * vis.text_l + 0.55 * 0.04))
        raw_bleed = 0.35 * backdrop.median + 0.65 * sample_low
        dark_pull = (1.0 - max(0.0, min(1.0, raw_bleed))) ** 0.58
        disturb_l = max(
            0.0,
            1.0 - dark_pull - 0.45 * backdrop.std - 1.10 * backdrop.edge_energy,
        )
        worst_l = max(0.0, 1.0 - ((1.0 - max(0.0, min(1.0, backdrop.p5))) ** 0.58) - 0.50 * backdrop.std)

    r_opaque = _ratio(cal_text_l, vis.bg_l)
    scale_norm = max(1.0, 10.5 / max(1.0, r_opaque))
    required_worst = max(2.5, effective_target * 0.68)

    # 5. Search for the lowest opacity 'a' in [floor, 1.0] that satisfies both:
    # - Primary criterion: Perceptual contrast against disturbing backdrop luminance >= effective_target
    # - Worst-case criterion: Perceptual contrast against extreme backdrop patches >= required_worst
    for a in np.arange(floor, 1.001, 0.05):
        r_primary = _ratio(cal_text_l, a * vis.bg_l + (1.0 - a) * disturb_l) * scale_norm
        r_worst = _ratio(cal_text_l, a * vis.bg_l + (1.0 - a) * worst_l) * scale_norm
        if r_primary >= effective_target and r_worst >= required_worst:
            return float(round(a, 2))

    return 1.0
