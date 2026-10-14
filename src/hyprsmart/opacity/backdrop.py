from dataclasses import dataclass
from pathlib import Path
import os
from threading import Lock

import numpy as np
from PIL import Image

from hyprsmart.primitive import Window

# monitor resolution downscale factor
DOWN = 4

# Cache for computed wallpaper (luminance, gradient): (path, monitor_w, monitor_h, mtime) -> (lum, grad)
WALLPAPER_CACHE: dict[tuple[str, int, int, float], tuple[np.ndarray, np.ndarray]] = {}
WALLPAPER_CACHE_LOCK = Lock()


def _luminance(rgb: np.ndarray) -> np.ndarray:
    """
    Convert an RGB image into a 2D array of relative luminance values.

    Each pixel's three RGB channels are converted into a single value
    representing its relative brightness, using the WCAG sRGB luminance formula.

    Args:
        rgb: NumPy array of shape (height, width, 3), containing RGB
            channel values in the range [0, 255].

    Returns:
        A 2D NumPy array of shape (height, width), containing relative
        luminance values in the range [0.0, 1.0].
    """
    # Normalize RGB channel values to [0.0, 1.0].
    c = rgb / 255.0

    # Convert nonlinear sRGB values into linear-light values.
    lin = np.where(
        c <= 0.04045,
        c / 12.92,
        ((c + 0.055) / 1.055) ** 2.4,
    )

    # Combine linear RGB channels using WCAG luminance weights.
    return (lin @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).astype(np.float32)


def compute_sobel_energy(lum: np.ndarray) -> np.ndarray:
    """
    Compute 2D spatial gradient magnitude using the Sobel filter in pure NumPy,
    enhanced with adjacent finite differences to handle single-pixel patterns.
    Returns an array of identical shape with gradient magnitudes normalized around [0.0, 1.0].
    """
    if lum.shape[0] < 3 or lum.shape[1] < 3:
        return np.zeros_like(lum, dtype=np.float32)

    # Standard Sobel X: [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]] / 8.0
    gx = (
        (lum[:-2, 2:] + 2.0 * lum[1:-1, 2:] + lum[2:, 2:])
        - (lum[:-2, :-2] + 2.0 * lum[1:-1, :-2] + lum[2:, :-2])
    ) / 8.0

    # Standard Sobel Y: [[-1, -2, -1], [0, 0, 0], [1, 2, 1]] / 8.0
    gy = (
        (lum[2:, :-2] + 2.0 * lum[2:, 1:-1] + lum[2:, 2:])
        - (lum[:-2, :-2] + 2.0 * lum[:-2, 1:-1] + lum[:-2, 2:])
    ) / 8.0

    sobel_mag = np.sqrt(gx**2 + gy**2)

    # Adjacent pixel differences to catch single-pixel checkerboards/stripes
    fdx = np.abs(lum[1:-1, 1:] - lum[1:-1, :-1])[:, :-1]
    fdy = np.abs(lum[1:, 1:-1] - lum[:-1, 1:-1])[:-1, :]
    fd = 0.5 * (fdx + fdy)

    mag = np.maximum(sobel_mag, fd)
    # Pad border to keep identical dimensions
    return np.pad(mag, ((1, 1), (1, 1)), mode="edge").astype(np.float32)


def load_wallpaper(path: str, monitor_w: int, monitor_h: int) -> np.ndarray:
    """
    Render a wallpaper in 'cover' mode, at reduced size (scaled down by DOWN),
    and calculate its WCAG relative luminance.
    """
    img = Image.open(path).convert("RGB")
    target_width = max(1, monitor_w // DOWN)
    target_height = max(1, monitor_h // DOWN)

    tw_scale = target_width / img.width
    th_scale = target_height / img.height
    scale_fact = max(th_scale, tw_scale)

    img = img.resize(
        (
            round(img.width * scale_fact),
            round(img.height * scale_fact),
        ),
        Image.LANCZOS,
    )

    left = (img.width - target_width) // 2
    top = (img.height - target_height) // 2

    img = img.crop((
        left,
        top,
        left + target_width,
        top + target_height,
    ))

    return _luminance(np.asarray(img, dtype=np.float32))


def get_cached_wallpaper_backdrop_data(
    path: str | None,
    monitor_w: int,
    monitor_h: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Retrieve or compute wallpaper (luminance, gradient_energy) from cache.
    Falls back to neutral background if no wallpaper is specified or found.
    """
    target_w = max(1, monitor_w // DOWN)
    target_h = max(1, monitor_h // DOWN)

    if not path or not os.path.exists(path):
        # Default neutral background: dark 0.2, zero gradient
        return (
            np.full((target_h, target_w), 0.2, dtype=np.float32),
            np.zeros((target_h, target_w), dtype=np.float32),
        )

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0

    cache_key = (path, monitor_w, monitor_h, mtime)
    with WALLPAPER_CACHE_LOCK:
        cached = WALLPAPER_CACHE.get(cache_key)
        if cached is not None:
            return cached

    try:
        lum = load_wallpaper(path, monitor_w, monitor_h)
        grad = compute_sobel_energy(lum)
        with WALLPAPER_CACHE_LOCK:
            WALLPAPER_CACHE[cache_key] = (lum, grad)
        return lum, grad
    except Exception as e:
        print(f"[WARN] Failed to load wallpaper from {path}: {e}")
        return (
            np.full((target_h, target_w), 0.2, dtype=np.float32),
            np.zeros((target_h, target_w), dtype=np.float32),
        )


def get_cached_wallpaper_luminance(
    path: str | None,
    monitor_w: int,
    monitor_h: int,
) -> np.ndarray:
    """Helper returning only the luminance map for backward compatibility."""
    lum, _ = get_cached_wallpaper_backdrop_data(path, monitor_w, monitor_h)
    return lum


def clear_wallpaper_cache() -> None:
    """Clear all cached wallpaper luminance matrices and gradient maps."""
    with WALLPAPER_CACHE_LOCK:
        WALLPAPER_CACHE.clear()


@dataclass
class Backdrop:
    p5: float          # 5th percentile (darkest background spots)
    p95: float         # 95th percentile (brightest background spots)
    p15: float         # 15th percentile (trimmed low level)
    p85: float         # 85th percentile (trimmed high level)
    median: float      # median background brightness
    std: float         # variance in brightness
    edge_energy: float # spatial high-frequency edge energy [0, 1]


def backdrop_behind(
    lum: np.ndarray,
    win: Window,
    monitor_x: int,
    monitor_y: int,
    grad: np.ndarray | None = None,
) -> Backdrop:
    """
    Extract the region of the monitor behind the passed window.
    Computes luminance percentiles and high-frequency edge energy.
    """
    h, w = lum.shape
    x0 = max(0, min(w, int((win.x - monitor_x) // DOWN)))
    y0 = max(0, min(h, int((win.y - monitor_y) // DOWN)))
    x1 = max(0, min(w, int((win.x - monitor_x + win.width) // DOWN)))
    y1 = max(0, min(h, int((win.y - monitor_y + win.height) // DOWN)))

    if x1 <= x0 or y1 <= y0:
        return Backdrop(
            p5=0.5, p95=0.5, p15=0.5, p85=0.5, median=0.5, std=0.0, edge_energy=0.0
        )

    # Note: NumPy indexing is [rows, columns] -> [y, x]
    region = lum[y0:y1, x0:x1]

    if region.size == 0:
        return Backdrop(
            p5=0.5, p95=0.5, p15=0.5, p85=0.5, median=0.5, std=0.0, edge_energy=0.0
        )

    if grad is not None:
        region_grad = grad[y0:y1, x0:x1]
    else:
        region_grad = compute_sobel_energy(lum)[y0:y1, x0:x1]

    p5, p15, median, p85, p95 = np.percentile(region, [5, 15, 50, 85, 95])
    edge_energy = float(np.mean(region_grad))

    return Backdrop(
        p5=float(p5),
        p95=float(p95),
        p15=float(p15),
        p85=float(p85),
        median=float(median),
        std=float(region.std()),
        edge_energy=edge_energy,
    )
