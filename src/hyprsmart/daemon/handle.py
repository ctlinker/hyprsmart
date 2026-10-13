from queue import Queue
from threading import Thread, Timer

from .socket import HyprEvent

from hyprsmart.primitive import (
    get_hyprland_active_window,
    get_hyprland_active_monitor,
    set_hyprland_win_opacity,
    capture_window
)

from hyprsmart.opacity import (
    decide_opacity,
    load_wallpaper,
    window_colors,
    backdrop_behind
)

CAPTURE_QUEUE = Queue()
MODEL_QUEUE = Queue()
EVENT_DELAYS = {
    "activewindowv2": 0.2,
    "openwindow": 0.4,
    "windowtitlev2": 0.3,
    "fullscreen": 0.2,
    "changefloatingmode": 0.2,
}

def handle_event(ev: HyprEvent):
    delay = EVENT_DELAYS.get(ev.kind)

    if delay is None:
        print("skipped:", ev.kind)
        return

    print("handled:", ev.kind, "delay:", delay)
    Timer(delay, schedule_capture).start()
    

def schedule_capture():
    win = get_hyprland_active_window()

    if win is None:
        return
    
    CAPTURE_QUEUE.put(win)

def capture_worker():
    while True:
        win = CAPTURE_QUEUE.get()

        try:
            img = capture_window(win)
            MODEL_QUEUE.put((win, img))
        
        except Exception:
            print("[WARN]Failed to capture window")

        finally:
            CAPTURE_QUEUE.task_done()


def luminance_worker():
    while True:
        
        mon = get_hyprland_active_monitor()
        if mon is None:
            continue

        win, img = MODEL_QUEUE.get()
        text_l, bg_l = window_colors(img)

        wallpaper_lum = load_wallpaper(
            "/home/char-c/Pictures/Wallpapers/red-flower-field-live-wallpaper.gif", 
            mon.width, 
            mon.height
        )

        b = backdrop_behind(wallpaper_lum, win, mon.x, mon.y)
        alpha = decide_opacity(text_l, bg_l, b)
        print(f"decided: {alpha}, {win.address}")
        set_hyprland_win_opacity(win.address, alpha, alpha)

        MODEL_QUEUE.task_done()

def model_worker():
    while True:
        win, img = MODEL_QUEUE.get()

        try:
            # state = analyze_window_img(img)
            # save_sample(win, img, state)
        
        # except Exception:
            print("[WARN]Failed to capture window")

        finally:
            MODEL_QUEUE.task_done()

def load_hyprsmart_daemons():
    Thread(target=capture_worker, daemon=True).start()
    Thread(target=luminance_worker, daemon=True).start()


