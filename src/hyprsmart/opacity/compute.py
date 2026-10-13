from .backdrop import Backdrop
import numpy as np

def _ratio(a: float, b: float) -> float:
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)

def decide_opacity(text_l: float, bg_l: float, b: Backdrop,
                   target: float = 4.5, floor: float = 0.5) -> float:
    for a in np.arange(floor, 1.001, 0.05):
        worst = min(_ratio(text_l, a * bg_l + (1 - a) * x) for x in (b.p5, b.p95))
        if worst >= target:
            return float(a)
    return 1.0
