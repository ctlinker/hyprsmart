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
        print("handled")
        Timer(schedule_capture(), 0.1).run()
    else:
        print("skipped")
    

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
        finally:
            CAPTURE_QUEUE.task_done()

def model_worker():
    while True:
        win, img = MODEL_QUEUE.get()

        try:
            state = analyze_window_img(img)
            save_sample(win, img, state)
        finally:
            MODEL_QUEUE.task_done()

def load_hyprsmart_daemons():
    Thread(target=capture_worker, daemon=True).start()
    Thread(target=model_worker, daemon=True).start()


