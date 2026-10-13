import io
import numpy as np
from PIL import Image
from .backdrop import _luminance  # same function as before

def window_colors(img_bytes: bytes) -> tuple[float, float]:
    """Returns (text_l, bg_l) from a window screenshot."""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img.thumbnail((512, 512))
    rgb = np.asarray(img)

    # 1. background = most common color (colors rounded to 16 levels per channel,
    #    so tiny gradients/noise count as the same color)
    q = (rgb >> 4).reshape(-1, 3).astype(np.int32)
    packed = (q[:, 0] << 8) | (q[:, 1] << 4) | q[:, 2]
    vals, counts = np.unique(packed, return_counts=True)
    top = vals[counts.argmax()]
    bg_rgb = np.array([(top >> 8) & 15, (top >> 4) & 15, top & 15]) * 16 + 8
    bg_l = float(_luminance(bg_rgb.astype(np.float32)))

    # 2. text = the extreme pixels on the opposite side of the background
    lum = _luminance(rgb.astype(np.float32))
    text_l = float(np.percentile(lum, 99 if bg_l < 0.5 else 1))

    return text_l, bg_l
