from PIL import Image
import numpy as np

# purspose : monitor resoltion downscale factor
DOWN = 4

def _luminance(rgb: np.ndarray) -> np.ndarray:
    """
    Convert an RGB image into a 2D array of relative luminance values.

    Each pixel's three RGB channels are converted into a single value
    representing its relative brightness, using the WCAG sRGB luminance
    formula.

    Args:
        rgb: NumPy array of shape (height, width, 3), containing RGB
            channel values in the range [0, 255].

    Returns:
        A 2D NumPy array of shape (height, width), containing relative
        luminance values in the range [0.0, 1.0], where 0.0 represents
        black and 1.0 represents white.

    Processing:
        1. Normalize RGB values from [0, 255] to [0.0, 1.0].
        2. Convert sRGB channel values to linear-light values.
        3. Combine the linear RGB channels using WCAG luminance weights.

    Reference:
        WCAG 2.x — Relative luminance:
        https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
    """
    # Normalize RGB channel values to [0.0, 1.0].
    c = rgb / 255.0

    # Convert nonlinear sRGB values into linear-light values.
    # The piecewise formula accounts for the sRGB transfer function.
    lin = np.where(
        c <= 0.04045,
        c / 12.92,
        ((c + 0.055) / 1.055) ** 2.4,
    )

    # Combine the linear RGB channels into one luminance value per pixel.
    # The weights reflect the relative contributions of each channel.
    return lin @ np.array([0.2126, 0.7152, 0.0722])
    

def load_wallpaper(path: str, monitor_h: int, monitor_w: int):
    """
    render a wallpaper in 'cover' mode, at reduced size,
    And calculate it's WCAG relative luminance.
    Call once per wallpaper/monitor change.
    """

    img = Image.open(path).convert("RGB")
    target_width = monitor_w // DOWN
    target_height = monitor_h // DOWN

    tw_scale = target_width / img.width
    th_scale = target_height / img.height
    scale_fact = max(th_scale, tw_scale)

    img = img.resize((
        round(img.width * scale_fact), 
        round(img.height * scale_fact)
    ), Image.LANCZOS)

    left = (img.width - target_width) // 2
    top = (img.height - target_height) // 2

    img = img.crop((
        left,
        top,
        left + target_width,
        top + target_height
    ))

    return _luminance(np.ndarray(img, dtype=np.float32))