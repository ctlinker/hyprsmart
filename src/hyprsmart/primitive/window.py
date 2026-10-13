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

def window_from_hyprctl_json_dict(win: dict | None) -> Window | None:
    if not win or not isinstance(win, dict) or "title" not in win or "address" not in win:
        return None
    
    return Window(
        win.get("title", ""),
        win["address"],
        win.get("at", [0, 0])[0],
        win.get("at", [0, 0])[1],
        win.get("size", [0, 0])[0],
        win.get("size", [0, 0])[1],
    )

def window_from_hyprctl_json_string(w_str: str) -> Window | None:
    try:
        data = json.loads(w_str)
        return window_from_hyprctl_json_dict(data)
    except Exception:
        return None

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
