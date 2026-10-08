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

def window_from_hyprctl_json_dict(win: dict) -> Window:
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