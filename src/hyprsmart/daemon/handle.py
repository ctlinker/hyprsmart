from queue import Queue, Empty
from threading import Thread, Timer, Event, Lock
from time import time

from hyprsmart.config import get_current_config
from hyprsmart.opacity import (
    backdrop_behind,
    decide_opacity,
    get_cached_wallpaper_backdrop_data,
    window_colors,
)
from hyprsmart.primitive import (
    capture_window,
    get_hyprland_active_monitor,
    get_hyprland_active_window,
    set_hyprland_win_opacity,
)

from .cache import cache_drop, cache_get, cache_put, cache_clear
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
    "openwindow": 1.5,
}

MANAGED_WINDOWS: set[str] = set()
MANAGED_LOCK = Lock()

STOP_EVENT = Event()


def record_managed_window(address: str) -> None:
    with MANAGED_LOCK:
        MANAGED_WINDOWS.add(address)


def restore_all_managed_windows() -> None:
    """Reset opacity to 1.0 for all windows managed by HyprSmart."""
    with MANAGED_LOCK:
        addresses = list(MANAGED_WINDOWS)
        MANAGED_WINDOWS.clear()

    for addr in addresses:
        try:
            set_hyprland_win_opacity(addr, 1.0, 1.0)
            print(f"[INFO] Restored window opacity for {addr}")
        except Exception as e:
            print(f"[WARN] Failed to restore opacity for {addr}: {e}")


def debounce_ev(kind: str) -> bool:
    debounced = DEBOUNCE_STORE.get(kind)
    curr_time = time()

    if not debounced:
        DEBOUNCE_STORE[kind] = curr_time
        return True

    cfg = get_current_config()
    interval = cfg.debounce_interval if cfg else DEBOUNCE_INTERVAL

    if curr_time - debounced < interval:
        return False

    DEBOUNCE_STORE[kind] = curr_time
    return True


def handle_event(ev: HyprEvent) -> None:
    if STOP_EVENT.is_set():
        return

    if not debounce_ev(ev.kind):
        return

    delay = EVENT_DELAYS.get(ev.kind)
    if delay is None:
        return

    if ev.kind in ["openwindow", "windowtitlev2"]:
        Timer(delay, force_schedule_capture).start()
    elif ev.kind == "activewindowv2":
        Timer(delay, schedule_capture).start()


def force_schedule_capture() -> None:
    schedule_capture(force=True)


def schedule_capture(force: bool = False) -> None:
    if STOP_EVENT.is_set():
        return
    win = get_hyprland_active_window()
    if win is None:
        return
    if not force and (e := cache_get(win)):
        CACHE_HIT_QUEUE.put((win, e))
        return
    CAPTURE_QUEUE.put(win)


def capture_worker() -> None:
    while not STOP_EVENT.is_set():
        try:
            win = CAPTURE_QUEUE.get(timeout=1.0)
        except Empty:
            continue

        try:
            img = capture_window(win)
            LUMINANCE_QUEUE.put((win, img))
        except Exception:
            print("[WARN] Failed to capture window")
        finally:
            CAPTURE_QUEUE.task_done()


def cache_hit_worker() -> None:
    while not STOP_EVENT.is_set():
        try:
            win, w_entry = CACHE_HIT_QUEUE.get(timeout=1.0)
        except Empty:
            continue

        try:
            mon = get_hyprland_active_monitor()
            if mon is None:
                continue

            cfg = get_current_config()
            wall_path = cfg.get_wallpaper(mon.name, mon.id)
            wall_lum, wall_grad = get_cached_wallpaper_backdrop_data(wall_path, mon.width, mon.height)

            b = backdrop_behind(wall_lum, win, mon.x, mon.y, grad=wall_grad)
            alpha = decide_opacity(
                w_entry.visuals,
                b,
                target=cfg.target_contrast,
                floor=cfg.floor_opacity,
            )
            vis = w_entry.visuals
            print(
                f"[DECIDE] (cache hit) alpha: {alpha:.2f} "
                f"(text_dens={vis.text_density:.2f}, bg_ratio={vis.bg_ratio:.2f}, wall_edge={b.edge_energy:.3f}) "
                f"for {win.address}"
            )
            set_hyprland_win_opacity(win.address, alpha, alpha)
            record_managed_window(win.address)
        except Exception as e:
            print(f"[WARN] Error in cache_hit_worker: {e}")
        finally:
            CACHE_HIT_QUEUE.task_done()


def luminance_worker() -> None:
    while not STOP_EVENT.is_set():
        try:
            win, img = LUMINANCE_QUEUE.get(timeout=1.0)
        except Empty:
            continue

        try:
            mon = get_hyprland_active_monitor()
            if mon is None:
                continue

            visuals = window_colors(img)
            cache_put(win, visuals)

            cfg = get_current_config()
            wall_path = cfg.get_wallpaper(mon.name, mon.id)
            wall_lum, wall_grad = get_cached_wallpaper_backdrop_data(wall_path, mon.width, mon.height)

            b = backdrop_behind(wall_lum, win, mon.x, mon.y, grad=wall_grad)
            alpha = decide_opacity(
                visuals,
                b,
                target=cfg.target_contrast,
                floor=cfg.floor_opacity,
            )
            print(
                f"[DECIDE] alpha: {alpha:.2f} "
                f"(text_dens={visuals.text_density:.2f}, bg_ratio={visuals.bg_ratio:.2f}, wall_edge={b.edge_energy:.3f}) "
                f"for {win.address}"
            )
            set_hyprland_win_opacity(win.address, alpha, alpha)
            record_managed_window(win.address)
        except Exception as e:
            print(f"[WARN] Error in luminance_worker: {e}")
        finally:
            LUMINANCE_QUEUE.task_done()


def load_hyprsmart_daemons() -> None:
    STOP_EVENT.clear()
    Thread(target=capture_worker, daemon=True).start()
    Thread(target=cache_hit_worker, daemon=True).start()
    Thread(target=luminance_worker, daemon=True).start()
    print("[INFO] Started HyprSmart workers")
    Timer(0.5, schedule_capture).start()


def stop_hyprsmart_daemons() -> None:
    STOP_EVENT.set()
    restore_all_managed_windows()
