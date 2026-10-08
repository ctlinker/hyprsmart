from dataclasses import dataclass
import json
import subprocess
from io import BytesIO
from PIL import Image
from collections.abc import Callable

@dataclass
class Window:
    title: str
    address: str
    x: float
    y: float
    width: float
    height: float



def _default_hyprland_filter_win(win: dict) -> bool:
    return not win["hidden"] and win["visible"]


def get_hyprland_active_workspace_id() -> int:
    result = subprocess.run(
        ["hyprctl", "activeworkspace", "-j"],
        capture_output=True,
        check=True,
    )

    return json.loads(result.stdout)["id"]


def _filter_hyprland_win_by_focused_workspace():
    workspace_id = get_hyprland_active_workspace_id()
    
    return lambda win: win["workspace"]["id"] == workspace_id


def _filter_compute_filters(filters):
    def predicate(win):
        return all(filter_fn(win) for filter_fn in filters)

    return predicate


def get_hyprland_windows(
    filter_fn: Callable[[dict], bool] | None = None,
):
    if filter_fn is None:
        filter_fn = _filter_compute_filters([
            _default_hyprland_filter_win,
            _filter_hyprland_win_by_focused_workspace(),
        ])

    result = subprocess.run(
        ["hyprctl", "clients", "-j"],
        capture_output=True,
        check=True,
    )

    win_dicts = filter(filter_fn, json.loads(result.stdout))

    return [
        Window(
            win["title"],
            win["address"],
            win["at"][0],
            win["at"][1],
            win["size"][0],
            win["size"][1],
        )
        for win in win_dicts
    ]

def capture_window(window: Window):
    geometry = f"{window.x},{window.y} {window.width}x{window.height}"

    result = subprocess.run(
        ["grim", "-g", geometry, "-"],
        capture_output=True,
        check=True,
    )

    return result.stdout