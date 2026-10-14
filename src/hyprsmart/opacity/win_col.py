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


def window_colors(img_bytes: bytes) -> WindowVisuals:
    """
    Extract color characteristics, text density, and background dominance from a window screenshot.
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
    bg_l = float(_luminance(bg_rgb.astype(np.float32)))

    # 2. Text luminance = extreme pixels on the opposite end of background luminance
    lum = _luminance(rgb.astype(np.float32))
    text_l = float(np.percentile(lum, 99 if bg_l < 0.5 else 1))

    # 3. Text density = ratio of pixels with sharp high-frequency edges
    grad = compute_sobel_energy(lum)
    text_density = float(np.mean(grad > 0.08))

    return WindowVisuals(
        text_l=text_l,
        bg_l=bg_l,
        text_density=text_density,
        bg_ratio=bg_ratio,
    )
