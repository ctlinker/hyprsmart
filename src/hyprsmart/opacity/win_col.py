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

    def __iter__(self):
        """Allows unpacking as (text_l, bg_l) for backward compatibility."""
        yield self.text_l
        yield self.bg_l


def unblend_luminance(
    captured_l: float,
    alpha: float,
    backdrop_l: float | None,
    class_ref_l: float | None = None,
) -> float:
    """
    Invert alpha compositing: L_captured = alpha * L_pure + (1 - alpha) * L_backdrop.
    Solves for L_pure = (L_captured - (1 - alpha) * L_backdrop) / alpha.
    Regularizes with class_ref_l when alpha is low.
    """
    if alpha >= 0.99 or backdrop_l is None:
        return float(np.clip(captured_l, 0.0, 1.0))

    safe_alpha = max(0.20, float(alpha))
    unblended = (captured_l - (1.0 - safe_alpha) * backdrop_l) / safe_alpha
    unblended = float(np.clip(unblended, 0.0, 1.0))

    if class_ref_l is not None:
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
    img.thumbnail((512, 512))
    rgb = np.asarray(img)

    # 1. Background = most common color (quantized to 16 levels per channel to smooth noise)
    q = (rgb >> 4).reshape(-1, 3).astype(np.int32)
    packed = (q[:, 0] << 8) | (q[:, 1] << 4) | q[:, 2]
    vals, counts = np.unique(packed, return_counts=True)
    top_idx = counts.argmax()
    top = vals[top_idx]
    bg_ratio = float(counts[top_idx] / len(packed))

    bg_rgb = np.array([(top >> 8) & 15, (top >> 4) & 15, top & 15]) * 16 + 8
    raw_bg_l = float(_luminance(bg_rgb.astype(np.float32)))

    # 2. Text luminance = extreme pixels on the opposite end of background luminance
    lum = _luminance(rgb.astype(np.float32))
    raw_text_l = float(np.percentile(lum, 99 if raw_bg_l < 0.5 else 1))

    # 3. Text density = ratio of pixels with sharp high-frequency edges
    grad = compute_sobel_energy(lum)
    text_density = float(np.mean(grad > 0.08))

    # 4. Optical unblending if window is currently transparent
    ref_bg = class_ref.bg_l if class_ref else None
    ref_text = class_ref.text_l if class_ref else None

    bg_l = unblend_luminance(raw_bg_l, current_alpha, backdrop_median, ref_bg)
    text_l = unblend_luminance(raw_text_l, current_alpha, backdrop_median, ref_text)

    return WindowVisuals(
        text_l=bg_l if bg_l == text_l else text_l,
        bg_l=bg_l,
        text_density=text_density,
        bg_ratio=bg_ratio,
    )
