from dataclasses import dataclass

@dataclass
class VisualState:
    video: bool
    text_density: float
    visual_density: float
    contrast: float

def decide_opacity(state: VisualState) -> float:
    if state.video:
        return 1.0

    if state.text_density > 0.7:
        return 1.0

    if state.visual_density > 0.8:
        return 0.95

    return 0.85