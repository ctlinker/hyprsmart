from dataclasses import dataclass
import subprocess
import json

@dataclass
class Monitor:
    id: int
    name: str
    x: int
    y: int
    width: int
    height: int
    scale: float


def get_hyprland_monitors() -> list[Monitor]:
    result = subprocess.run(
        ["hyprctl", "monitors", "-j"],
        capture_output=True,
        text=True,
        check=True,
    )
    monitors_data = json.loads(result.stdout)
    return [
        Monitor(
            id=m.get("id", 0),
            name=m["name"],
            x=m["x"],
            y=m["y"],
            width=m["width"],
            height=m["height"],
            scale=float(m["scale"]),
        )
        for m in monitors_data
    ]


def get_hyprland_active_monitor() -> Monitor | None:
    result = subprocess.run(
        ["hyprctl", "monitors", "-j"],
        capture_output=True,
        text=True,
        check=True,
    )

    monitors = json.loads(result.stdout)
    monitor = next(
        (m for m in monitors if m.get("focused")),
        None,
    )

    if monitor is None:
        return None

    return Monitor(
        id=monitor.get("id", 0),
        name=monitor["name"],
        x=monitor["x"],
        y=monitor["y"],
        width=monitor["width"],
        height=monitor["height"],
        scale=float(monitor["scale"]),
    )
