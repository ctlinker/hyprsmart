from queue import Queue
from threading import Thread, Timer

from hyprsmart import (
    HyprEvent,
    analyze_window_img,
    capture_window,
    get_hyprland_active_window,
)

from .datacollect import save_sample

CAPTURE_QUEUE = Queue()
MODEL_QUEUE = Queue()
EVENT_DELAYS = {
    "activewindowv2": 0.1,
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

def model_worker():
    while True:
        win, img = MODEL_QUEUE.get()

        try:
            state = analyze_window_img(img)
            save_sample(win, img, state)
        
        except Exception:
            print("[WARN]Failed to capture window")

        finally:
            MODEL_QUEUE.task_done()

def load_hyprsmart_daemons():
    Thread(target=capture_worker, daemon=True).start()
    Thread(target=model_worker, daemon=True).start()


