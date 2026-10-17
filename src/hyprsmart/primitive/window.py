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
    pid: int = 0
    inhibiting_idle: bool = False
    fullscreen: bool = False
    window_class: str = ""
    monitor_id: int = 0

def window_from_hyprctl_json_dict(win: dict | None) -> Window | None:
    if not win or not isinstance(win, dict) or "title" not in win or "address" not in win:
        return None
    
    return Window(
        title=win.get("title", ""),
        address=win["address"],
        x=float(win.get("at", [0, 0])[0]),
        y=float(win.get("at", [0, 0])[1]),
        width=float(win.get("size", [0, 0])[0]),
        height=float(win.get("size", [0, 0])[1]),
        pid=int(win.get("pid", 0) or 0),
        inhibiting_idle=bool(win.get("inhibitingIdle", False)),
        fullscreen=bool(win.get("fullscreen", False) or win.get("fullscreenClient", False)),
        window_class=str(win.get("class", "")),
        monitor_id=int(win.get("monitor", 0) or 0),
    )

def window_from_hyprctl_json_string(w_str: str) -> Window | None:
    try:
        data = json.loads(w_str)
        return window_from_hyprctl_json_dict(data)
    except Exception:
        return None

def capture_window(window: Window) -> bytes:
    gx = int(round(window.x))
    gy = int(round(window.y))
    gw = int(round(window.width))
    gh = int(round(window.height))
    geometry = f"{gx},{gy} {gw}x{gh}"

    result = subprocess.run(
        ["grim", "-g", geometry, "-"],
        capture_output=True,
        check=True,
    )

    return result.stdout


import re

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{1,16}$")
VALID_PROPS = {"opacity", "opacity_inactive"}


def set_hyprland_win_opacity(
    address: str,
    opacity: float,
    opacity_inactive: float,
) -> None:
    if not address or not ADDRESS_RE.match(address):
        raise ValueError(f"Invalid or unsafe window address: {address!r}")

    for prop, value in (
        ("opacity", opacity),
        ("opacity_inactive", opacity_inactive),
    ):
        if prop not in VALID_PROPS:
            raise ValueError(f"Invalid property: {prop}")
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
