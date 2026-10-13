from dataclasses import dataclass
import subprocess
import json

@dataclass
class Window:
    title: str
    address: str
    x: float
    y: float
    width: float
    height: float

def window_from_hyprctl_json_dict(win: dict | None) -> Window|None:
    if win is None:
        return None
    
    return Window(
            win["title"],
            win["address"],
            win["at"][0],
            win["at"][1],
            win["size"][0],
            win["size"][1],
        )

def window_from_hyprctl_json_string(w_str: str) -> Window:
    return window_from_hyprctl_json_dict(json.loads(w_str))

def capture_window(window: Window) -> bytes:
    geometry = f"{window.x},{window.y} {window.width}x{window.height}"

    result = subprocess.run(
        ["grim", "-g", geometry, "-"],
        capture_output=True,
        check=True,
    )

    return result.stdout


def set_hyprland_win_opacity(
    address: str,
    opacity: float,
    opacity_inactive: float,
) -> None:
    for prop, value in (
        ("opacity", opacity),
        ("opacity_inactive", opacity_inactive),
    ):
        if not 0.0 <= value <= 1.1:
            raise ValueError(f"{prop} must be between 0.0 and 1.0")

        subprocess.run(
            [
                "hyprctl",
                "dispatch",
                f'hl.dsp.window.set_prop({{ window = "address:{address}", prop = "{prop}", value = {value} }})',
            ],
            check=True,
            capture_output=True,
            text=True,
        )
