from io import BytesIO

from PIL import Image

from .window import capture_window
from .w_getter import get_hyprland_active_window
from .socket import listen_hyprland_socket, HyprEvent
from .opacity import analyze_window_img, decide_opacity

ANALYSIS_EVENTS = {
    "activewindowv2",
    "openwindow",
    "windowtitlev2",
    "fullscreen",
    "changefloatingmode",
}

def handle_event(ev: HyprEvent):
    print(ev)
    if ev.kind in ANALYSIS_EVENTS:
        win = get_hyprland_active_window()

        if win is None:
            return

        img = capture_window(win)
        state = analyze_window_img(img)

        print(state)
        # print("opacity:", decide_opacity(state))

    print("done")


def main() -> None:
    listen_hyprland_socket(handle_event)
