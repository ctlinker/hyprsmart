from dataclasses import dataclass
import subprocess
import json

@dataclass
class Monitor:
    name: str
    x: int
    y: int
    width: int
    height: int
    scale: float


def get_hyprland_active_monitor() -> Monitor | None:
    result = subprocess.run(
        ["hyprctl", "monitors", "-j"],
        capture_output=True,
        text=True,
        check=True,
    )

    monitors = json.loads(result.stdout)
    monitor = next(
        (m for m in monitors if m["focused"]),
        None,
    )

    if monitor is None:
        return None

    return Monitor(
        name=monitor["name"],
        x=monitor["x"],
        y=monitor["y"],
        width=monitor["width"],
        height=monitor["height"],
        scale=monitor["scale"],
    )
