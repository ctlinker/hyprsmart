from dataclasses import dataclass
import io
import numpy as np
from PIL import Image

from .backdrop import _luminance, compute_sobel_energy


@dataclass
class WindowVisuals:
    text_l: float        # Relative luminance of the foreground text/elements [0, 1]
    bg_l: float          # Relative luminance of the dominant background [0, 1]
    text_density: float  # Estimated ratio of window surface containing glyph edges [0, 1]
    bg_ratio: float      # Proportion of the window covered by the dominant background color [0, 1]
    volatility: float = 0.0    # Learned EMA of intra-session visual delta [0, 1]
    settle_time: float = 0.0   # Learned EMA of seconds until visual convergence [0, 30]
    sample_count: int = 0      # Number of progressive sessions observed for this class

    def __iter__(self):
        """Allows unpacking as (text_l, bg_l) for backward compatibility."""
        yield self.text_l
        yield self.bg_l


def visual_delta(v1: WindowVisuals, v2: WindowVisuals) -> float:
    """
    Compute the perceptual change across visual dimensions.
    Luminance shifts (background and text polarity) are weighted at 1.0,
    while spatial texture variations (glyph density and background ratio)
    are scaled to 0.50 to prevent cursors/carousel micro-noise from inflating delta.
    """
    return float(
        max(
            abs(v1.bg_l - v2.bg_l),
            abs(v1.text_l - v2.text_l),
            0.50 * abs(v1.bg_ratio - v2.bg_ratio),
            0.50 * abs(v1.text_density - v2.text_density),
        )
    )


def unblend_luminance(
    captured_l: float,
    alpha: float,
    backdrop_l: float | None,
    class_ref_l: float | None = None,
) -> float:
    """
    Invert alpha compositing: L_captured = alpha * L_pure + (1 - alpha) * L_backdrop.
    Solves for L_pure = (L_captured - (1 - alpha) * L_backdrop) / alpha.
    Regularizes with class_ref_l when alpha is low, unless a polarity/theme flip is detected.
    """
    if alpha >= 0.99 or backdrop_l is None:
        return float(np.clip(captured_l, 0.0, 1.0))

    safe_alpha = max(0.20, float(alpha))
    unblended = (captured_l - (1.0 - safe_alpha) * backdrop_l) / safe_alpha
    unblended = float(np.clip(unblended, 0.0, 1.0))

    if class_ref_l is not None:
        # Bypass class_ref anchoring if a polarity flip (e.g. dark loading screen -> white page) occurs
        if abs(unblended - class_ref_l) > 0.25:
            return unblended
        w_ref = max(0.0, min(0.35, (0.80 - safe_alpha) * 0.5))
        final_l = (1.0 - w_ref) * unblended + w_ref * class_ref_l
        return float(np.clip(final_l, 0.0, 1.0))

    return unblended


def window_colors(
    img_bytes: bytes,
    current_alpha: float = 1.0,
    backdrop_median: float | None = None,
    class_ref: WindowVisuals | None = None,
) -> WindowVisuals:
    """
    Extract color characteristics, text density, and background dominance from a window screenshot.
    Performs optical unblending if the window is currently transparent (current_alpha < 1.0).
    """
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    # Use NEAREST resampling to preserve crisp 1-2px font glyph cores without blending into background
    img.thumbnail((640, 640), Image.Resampling.NEAREST)
    rgb = np.asarray(img)
    flat_rgb = rgb.reshape(-1, 3).astype(np.float32)

    # 1. Dominant background seed via 12-bit quantization, then refine with neighborhood cluster
    #    to eliminate 4-bit quantization boundary splitting (e.g. RGB 31 vs 32) and wallpaper bleed.
    q = (rgb >> 4).reshape(-1, 3).astype(np.int32)
    packed = (q[:, 0] << 8) | (q[:, 1] << 4) | q[:, 2]
    vals, counts = np.unique(packed, return_counts=True)
    top_idx = counts.argmax()
    top = vals[top_idx]

    seed_mask = packed == top
    seed_rgb = flat_rgb[seed_mask].mean(axis=0)
    raw_bg_l = float(_luminance(seed_rgb))

    lum = _luminance(rgb)
    grad = compute_sobel_energy(lum)

    safe_alpha = max(0.20, min(1.0, float(current_alpha)))
    bleed_allowance = 1.0 - safe_alpha

    # Include neighboring bins within perceptual RGB/luminance tolerance on smooth (non-edge) surfaces
    rgb_tol = 22.0 + bleed_allowance * 75.0
    lum_tol = 0.045 + bleed_allowance * 0.22
    smooth_mask = grad <= 0.07
    bg_cluster_mask = np.zeros(lum.shape, dtype=bool)
    if np.any(smooth_mask):
        lum_diff_smooth = np.abs(lum[smooth_mask] - raw_bg_l)
        flat_rgb_smooth = flat_rgb[smooth_mask.ravel()]
        rgb_dist_smooth = np.max(np.abs(flat_rgb_smooth - seed_rgb), axis=1)
        bg_cluster_mask[smooth_mask] = (rgb_dist_smooth <= rgb_tol) | (lum_diff_smooth <= lum_tol)

    cluster_bg_ratio = float(np.mean(bg_cluster_mask))
    single_bin_ratio = float(counts[top_idx] / len(packed))
    bg_ratio = max(single_bin_ratio, cluster_bg_ratio)

    # Refine raw_bg_l using median of the smooth background cluster
    if np.any(bg_cluster_mask):
        raw_bg_l = float(np.median(lum[bg_cluster_mask]))

    # 2. Text luminance = directional foreground glyph extraction on the opposite side of background
    #    Use the 80th percentile of bright glyphs (or 20th of dark glyphs) to represent typical
    #    body text & syntax-highlighted tokens rather than only the 4% brightest pure-white highlights.
    if raw_bg_l < 0.5:
        glyph_candidates = lum[(grad > 0.08) & (lum > raw_bg_l + 0.06)]
        directional_non_bg = lum[lum > raw_bg_l + 0.05]
        if len(glyph_candidates) >= 20:
            raw_text_l = float(np.percentile(glyph_candidates, 80))
        elif len(directional_non_bg) > 30:
            raw_text_l = float(np.percentile(directional_non_bg, 85))
        else:
            raw_text_l = float(np.percentile(lum, 98.0))
    else:
        glyph_candidates = lum[(grad > 0.08) & (lum < raw_bg_l - 0.06)]
        directional_non_bg = lum[lum < raw_bg_l - 0.05]
        if len(glyph_candidates) >= 20:
            raw_text_l = float(np.percentile(glyph_candidates, 20))
        elif len(directional_non_bg) > 30:
            raw_text_l = float(np.percentile(directional_non_bg, 15))
        else:
            raw_text_l = float(np.percentile(lum, 2.0))

    # 3. Text density = ratio of pixels with sharp high-frequency edges
    text_density = float(np.mean(grad > 0.08))

    # 4. Optical unblending if window is currently transparent
    ref_bg = class_ref.bg_l if class_ref else None
    ref_text = class_ref.text_l if class_ref else None

    bg_l = unblend_luminance(raw_bg_l, current_alpha, backdrop_median, ref_bg)
    text_l = unblend_luminance(raw_text_l, current_alpha, backdrop_median, ref_text)

    # Regularize bg_ratio and text_density against class reference when captured transparent
    if current_alpha < 0.95 and class_ref is not None and abs(bg_l - class_ref.bg_l) <= 0.25:
        w_struct = max(0.0, min(0.50, (0.95 - safe_alpha) * 0.8))
        bg_ratio = float(np.clip(max(bg_ratio, (1.0 - w_struct) * bg_ratio + w_struct * class_ref.bg_ratio), 0.0, 1.0))
        text_density = float(np.clip((1.0 - w_struct) * text_density + w_struct * class_ref.text_density, 0.0, 1.0))

    # 5. Modest safety guard only for extreme degenerate captures (e.g. light-mode toolbar misread)
    if bg_ratio >= 0.35 and abs(text_l - bg_l) > 1e-4:
        if bg_l < 0.35 and text_l < 0.32:
            text_l = max(text_l, min(0.45, bg_l + 0.34))
        elif bg_l >= 0.50 and text_l > 0.25:
            text_l = min(text_l, max(0.08, bg_l - 0.55))

    return WindowVisuals(
        text_l=bg_l if bg_l == text_l else text_l,
        bg_l=bg_l,
        text_density=text_density,
        bg_ratio=bg_ratio,
    )
