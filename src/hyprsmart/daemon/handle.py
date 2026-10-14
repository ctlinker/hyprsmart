import time
from queue import Queue, Empty
from threading import Thread, Timer, Event, Lock

from hyprsmart.config import get_current_config
from hyprsmart.opacity import (
    backdrop_behind,
    decide_opacity,
    evaluate_video_score,
    get_cached_wallpaper_backdrop_data,
    window_colors,
    WindowVisuals,
)
from hyprsmart.primitive import (
    capture_window,
    get_hyprland_active_monitor,
    get_hyprland_active_window,
    set_hyprland_win_opacity,
    Window,
)

from .cache import (
    cache_clear,
    cache_drop,
    cache_get,
    cache_put,
    get_applied_alpha,
    record_applied_state,
)
from .socket import HyprEvent

CAPTURE_QUEUE = Queue()
LUMINANCE_QUEUE = Queue()
CACHE_HIT_QUEUE = Queue()

MANAGED_WINDOWS: set[str] = set()
MANAGED_LOCK = Lock()

STOP_EVENT = Event()

DIFF_OPACITY_THRESHOLD: float = 0.03


class DebouncedScheduler:
    """Per-target trailing debounce scheduler. Resets timer if new events arrive."""
    def __init__(self) -> None:
        self._timers: dict[str, Timer] = {}
        self._lock = Lock()

    def schedule(self, key: str, delay: float, target, *args, **kwargs) -> None:
        with self._lock:
            existing = self._timers.get(key)
            if existing:
                try:
                    existing.cancel()
                except Exception:
                    pass
            t = Timer(delay, self._run_and_clean, args=(key, target, args, kwargs))
            self._timers[key] = t
            t.start()

    def cancel(self, key: str) -> None:
        with self._lock:
            existing = self._timers.pop(key, None)
            if existing:
                try:
                    existing.cancel()
                except Exception:
                    pass

    def cancel_all(self) -> None:
        with self._lock:
            for t in self._timers.values():
                try:
                    t.cancel()
                except Exception:
                    pass
            self._timers.clear()

    def _run_and_clean(self, key: str, target, args, kwargs) -> None:
        with self._lock:
            self._timers.pop(key, None)
        if not STOP_EVENT.is_set():
            target(*args, **kwargs)


SCHEDULER = DebouncedScheduler()


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


def handle_event(ev: HyprEvent) -> None:
    if STOP_EVENT.is_set():
        return

    if ev.kind == "closewindow":
        addr = ev.content.strip().split(",")[0]
        SCHEDULER.cancel(addr)
        cache_drop(addr)
        return

    # Delays for trailing debounce
    if ev.kind == "activewindowv2":
        # Focus switch: quick reaction
        SCHEDULER.schedule("active_window", 0.15, schedule_capture, force=False)
    elif ev.kind == "windowtitlev2":
        # Title changes (typing in terminal, tab switching): trailing settle delay
        SCHEDULER.schedule("active_window", 0.35, schedule_capture, force=False)
    elif ev.kind == "openwindow":
        # New window opening: wait for window painting to settle
        SCHEDULER.schedule("active_window", 0.70, schedule_capture, force=False)
    elif ev.kind in ("fullscreen", "movewindowv2"):
        SCHEDULER.schedule("active_window", 0.20, schedule_capture, force=False)


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
            # Anti-contamination: if window was already set transparent,
            # briefly restore 1.0 so grim captures pristine window content.
            applied = get_applied_alpha(win.address)
            was_transparent = applied < 0.99
            if was_transparent:
                try:
                    set_hyprland_win_opacity(win.address, 1.0, 1.0)
                    time.sleep(0.02)
                except Exception:
                    pass

            img = capture_window(win)
            LUMINANCE_QUEUE.put((win, img))
        except Exception as e:
            print(f"[WARN] Failed to capture window {win.address}: {e}")
        finally:
            CAPTURE_QUEUE.task_done()


def apply_window_decision(win: Window, visuals: WindowVisuals, from_cache: bool = False) -> None:
    mon = get_hyprland_active_monitor()
    if mon is None:
        return

    cfg = get_current_config()
    is_video, v_score, _ = evaluate_video_score(win, visuals)

    b = None
    if is_video:
        ideal_alpha = cfg.video_opacity
    else:
        wall_path = cfg.get_wallpaper(mon.name, mon.id)
        wall_lum, wall_grad = get_cached_wallpaper_backdrop_data(wall_path, mon.width, mon.height)
        b = backdrop_behind(wall_lum, win, mon.x, mon.y, grad=wall_grad)
        ideal_alpha = decide_opacity(
            visuals,
            b,
            target=cfg.target_contrast,
            floor=cfg.floor_opacity,
        )

    # Opacity diffing: check if current opacity is already appropriate
    current_alpha = get_applied_alpha(win.address)
    alpha_diff = abs(ideal_alpha - current_alpha)
    backdrop_sig = (b.p15, b.p85, b.edge_energy) if b is not None else None
    geom = (int(win.x), int(win.y), int(win.width), int(win.height))

    if alpha_diff < DIFF_OPACITY_THRESHOLD:
        # Opacity is already appropriate: skip IPC dispatch
        record_applied_state(win.address, current_alpha, backdrop_sig, geom)
        record_managed_window(win.address)
        return

    # Apply new opacity
    if is_video:
        prefix = "(cache hit - VIDEO)" if from_cache else "(VIDEO DETECTED)"
        print(f"[DECIDE] {prefix} alpha: {ideal_alpha:.2f} (S={v_score:.2f}) for {win.address}")
    else:
        prefix = "(cache hit) " if from_cache else ""
        print(
            f"[DECIDE] {prefix}alpha: {ideal_alpha:.2f} "
            f"(text_dens={visuals.text_density:.2f}, bg_ratio={visuals.bg_ratio:.2f}, wall_edge={b.edge_energy:.3f}) "
            f"for {win.address}"
        )

    set_hyprland_win_opacity(win.address, ideal_alpha, ideal_alpha)
    record_applied_state(win.address, ideal_alpha, backdrop_sig, geom)
    record_managed_window(win.address)


def cache_hit_worker() -> None:
    while not STOP_EVENT.is_set():
        try:
            win, w_entry = CACHE_HIT_QUEUE.get(timeout=1.0)
        except Empty:
            continue

        try:
            apply_window_decision(win, w_entry.visuals, from_cache=True)
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
            visuals = window_colors(img)
            cache_put(win, visuals)
            apply_window_decision(win, visuals, from_cache=False)
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
    SCHEDULER.schedule("initial_startup", 0.5, schedule_capture, force=False)


def stop_hyprsmart_daemons() -> None:
    STOP_EVENT.set()
    SCHEDULER.cancel_all()
    restore_all_managed_windows()

