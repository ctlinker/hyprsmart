from queue import Queue
from threading import Thread, Timer
from time import time

from hyprsmart.opacity import (
    backdrop_behind,
    decide_opacity,
    load_wallpaper,
    window_colors,
)
from hyprsmart.primitive import (
    capture_window,
    get_hyprland_active_monitor,
    get_hyprland_active_window,
    set_hyprland_win_opacity,
)

from .cache import cache_drop, cache_get, cache_put
from .socket import HyprEvent

CAPTURE_QUEUE = Queue()
LUMINANCE_QUEUE = Queue()
CACHE_HIT_QUEUE = Queue()

DEBOUNCE_INTERVAL: float = 0.1
DEBOUNCE_STORE: dict[str, float] = {}

EVENT_DELAYS: dict[str, float] = {
    "activewindowv2": 0.3,
    "windowtitlev2": 0.4,
    "fullscreen": 0.2,
    "openwindow": 2,
}

def debounce_ev(kind: str)-> bool:
    debounced = DEBOUNCE_STORE.get(kind)
    curr_time = time()

    if not debounced:
        DEBOUNCE_STORE[kind] = curr_time
        return True

    if curr_time - debounced < DEBOUNCE_INTERVAL:
        return False
    
    DEBOUNCE_STORE[kind] = curr_time
    return True

def handle_event(ev: HyprEvent)-> None:
    if not debounce_ev(ev.kind):
        print(f"debounced: {ev.kind}")
        return

    delay = EVENT_DELAYS.get(ev.kind)
    if delay is None:
        print(f"skipped: {ev.kind}")
        return

    if ev.kind in ["openwindow", "windowtitlev2"]:
        Timer(delay, force_schedule_capture).start()
    
    if ev.kind == "activewindowv2":
        Timer(delay, schedule_capture).start()
    
    print(f"handled: {ev.kind}")

    
def force_schedule_capture():
    schedule_capture(True)

def schedule_capture(force=False):
    win = get_hyprland_active_window()
    if win is None:
        return
    if not force and (e := cache_get(win)):
        CACHE_HIT_QUEUE.put((win, e))   # saute la capture, va direct au calcul
        return
    CAPTURE_QUEUE.put(win)

def capture_worker():
    while True:
        win = CAPTURE_QUEUE.get()
        try:
            img = capture_window(win)
            LUMINANCE_QUEUE.put((win, img))
        except Exception:
            print("[WARN]Failed to capture window")
        finally:
            CAPTURE_QUEUE.task_done()

def cache_hit_worker():
    while True:
        win, w_entry = CACHE_HIT_QUEUE.get()
        mon = get_hyprland_active_monitor()
        if mon is None:
            continue

        wallpaper_lum = load_wallpaper(
            "/home/char-c/Pictures/Wallpapers/red-flower-field-live-wallpaper.gif", 
            mon.width, 
            mon.height
        )

        b = backdrop_behind(wallpaper_lum, win, mon.x, mon.y)
        alpha = decide_opacity(w_entry.text_l, w_entry.bg_l, b)
        print(f"decided: {alpha}, {win.address}")
        set_hyprland_win_opacity(win.address, alpha, alpha)
        CACHE_HIT_QUEUE.task_done()

def luminance_worker():
    while True:
        
        mon = get_hyprland_active_monitor()
        if mon is None:
            continue

        win, img = LUMINANCE_QUEUE.get()
        text_l, bg_l = window_colors(img)
        cache_put(win, text_l, bg_l)

        wallpaper_lum = load_wallpaper(
            "/home/char-c/Pictures/Wallpapers/red-flower-field-live-wallpaper.gif", 
            mon.width, 
            mon.height
        )

        b = backdrop_behind(wallpaper_lum, win, mon.x, mon.y)
        alpha = decide_opacity(text_l, bg_l, b)
        print(f"decided: {alpha}, {win.address}")
        set_hyprland_win_opacity(win.address, alpha, alpha)
        LUMINANCE_QUEUE.task_done()

def load_hyprsmart_daemons():
    Thread(target=capture_worker, daemon=True).start()
    Thread(target=cache_hit_worker, daemon=True).start()
    Thread(target=luminance_worker, daemon=True).start()   
    print("starting hyprsmart")
    Timer(0.5, schedule_capture).start()


