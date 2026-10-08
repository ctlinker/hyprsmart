import json
import subprocess
from collections.abc import Callable
from .window import Window, window_from_hyprctl_json_string, window_from_hyprctl_json_dict

def _default_hyprland_filter_win(win: dict) -> bool:
    return not win["hidden"] and win["visible"]

def get_hyprland_active_workspace_id() -> int:
    result = subprocess.run(
        ["hyprctl", "activeworkspace", "-j"],
        capture_output=True,
        check=True,
    )

    return json.loads(result.stdout)["id"]

def get_hyprland_active_window() -> Window:
    result = subprocess.run(
        ["hyprctl", "activewindow", "-j"],
        capture_output=True,
        check=True,
    )

    return window_from_hyprctl_json_string(result.stdout)

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
        window_from_hyprctl_json_dict(win)
        for win in win_dicts
    ]

