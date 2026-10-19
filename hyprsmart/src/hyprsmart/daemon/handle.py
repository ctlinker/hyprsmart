from dataclasses import dataclass
import io
import time
from queue import Queue, Empty, Full
from threading import Thread, Timer, Event, Lock
from typing import Any

import numpy as np
from PIL import Image

from hyprsmart.config import get_current_config, is_sensitive_window
from hyprsmart.opacity import (
    Backdrop,
    backdrop_behind,
    decide_opacity,
    evaluate_video_score,
    get_cached_wallpaper_backdrop_data,
    visual_delta,
    window_colors,
    WindowVisuals,
)
from hyprsmart.primitive import (
    capture_window,
    get_hyprland_active_monitor,
    get_hyprland_monitors,
    get_hyprland_active_window,
    get_hyprland_windows,
    set_hyprland_win_opacity,
    Monitor,
    Window,
)

from .cache import (
    cache_clear,
    cache_drop,
    cache_get,
    cache_put,
    get_adaptive_reeval_budget,
    get_applied_alpha,
    get_class_profile,
    record_applied_state,
    record_class_probing_session,
)
from .dev_trace import (
    get_dev_captures_dir,
    is_dev_mode,
    save_dev_decision_bundle,
    set_dev_mode,
)
from .socket import HyprEvent

# Bounded queues to prevent memory ballooning / OOM during rapid event floods
CAPTURE_QUEUE = Queue(maxsize=8)
LUMINANCE_QUEUE = Queue(maxsize=8)
CACHE_HIT_QUEUE = Queue(maxsize=8)


def _enqueue_capture(item: tuple) -> None:
    """Enqueue capture request, dropping the oldest uncaptured request if queue is full."""
    try:
        CAPTURE_QUEUE.put_nowait(item)
    except Full:
        try:
            _ = CAPTURE_QUEUE.get_nowait()
            CAPTURE_QUEUE.task_done()
        except Empty:
            pass
        try:
            CAPTURE_QUEUE.put_nowait(item)
        except Full:
            pass


def _enqueue_luminance(item: tuple) -> None:
    """Enqueue luminance analysis task, dropping oldest item if queue is saturated."""
    try:
        LUMINANCE_QUEUE.put_nowait(item)
    except Full:
        try:
            _ = LUMINANCE_QUEUE.get_nowait()
            LUMINANCE_QUEUE.task_done()
        except Empty:
            pass
        try:
            LUMINANCE_QUEUE.put_nowait(item)
        except Full:
            pass


MANAGED_WINDOWS: set[str] = set()
MANAGED_LOCK = Lock()

STOP_EVENT = Event()

DIFF_OPACITY_THRESHOLD: float = 0.03
PROGRESSIVE_DELTA_THRESHOLD: float = 0.03


def _quick_thumbnail_array(img_bytes: bytes | None) -> np.ndarray | None:
    """Decode PNG bytes into a tiny 32x32 int16 RGB array for fast pixel-identity comparison."""
    if not img_bytes:
        return None
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB").resize((32, 32), Image.Resampling.NEAREST)
        return np.asarray(img, dtype=np.int16)
    except Exception:
        return None


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
            t.daemon = True
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


@dataclass
class ProgressiveSession:
    address: str
    window_class: str
    title_at_start: str
    max_ticks: int
    stable_ticks_target: int
    interval: float
    current_tick: int = 0
    stable_ticks: int = 0
    last_change_tick: int = 0
    max_delta: float = 0.0
    initial_visuals: WindowVisuals | None = None
    last_visuals: WindowVisuals | None = None
    last_thumb_arr: np.ndarray | None = None
    last_geom: tuple[int, int, int, int] | None = None
    last_alpha: float = 1.0
    smoothed_alpha: float = 1.0
    cancelled: bool = False


class ProgressiveReevaluator:
    """
    Manages cancelable multi-second progressive re-evaluation sessions (default 11 ticks @ 1.0s,
    early-stopping after 8 consecutive stable ticks) to track slow-loading windows (e.g. browsers)
    and learn an emergent dynamic class profile (volatility & settle_time).
    """
    TIMER_KEY = "progressive_reeval"

    def __init__(self, scheduler: DebouncedScheduler) -> None:
        self._scheduler = scheduler
        self._lock = Lock()
        self._active_session: ProgressiveSession | None = None

    @property
    def active_session(self) -> ProgressiveSession | None:
        with self._lock:
            return self._active_session

    def cancel(self, address: str | None = None, commit_partial: bool = False) -> None:
        session_to_commit: ProgressiveSession | None = None
        with self._lock:
            if self._active_session is None:
                return
            if address is not None and self._active_session.address != address:
                return
            self._active_session.cancelled = True
            if commit_partial and self._active_session.current_tick >= 1 and self._active_session.last_visuals is not None:
                session_to_commit = self._active_session
            self._active_session = None
            self._scheduler.cancel(self.TIMER_KEY)

        if session_to_commit is not None and session_to_commit.window_class:
            settle_sec = session_to_commit.last_change_tick * session_to_commit.interval
            record_class_probing_session(
                session_to_commit.window_class,
                session_to_commit.last_visuals,
                max_delta=session_to_commit.max_delta,
                settle_time_sec=settle_sec,
                captured_alpha=session_to_commit.last_alpha,
            )

    def start_session(
        self,
        win: Window,
        initial_visuals: WindowVisuals | None = None,
        initial_thumb: np.ndarray | None = None,
        initial_alpha: float = 1.0,
    ) -> ProgressiveSession | None:
        if STOP_EVENT.is_set():
            return None

        cfg = get_current_config()
        max_ticks, stable_target = get_adaptive_reeval_budget(
            win.window_class,
            max_ticks_cfg=cfg.reeval_max_ticks,
            stable_ticks_cfg=cfg.reeval_stable_ticks,
        )
        if max_ticks <= 0:
            self.cancel()
            return None

        interval = max(0.1, float(cfg.reeval_interval))
        geom = (int(win.x), int(win.y), int(win.width), int(win.height))

        session = ProgressiveSession(
            address=win.address,
            window_class=win.window_class,
            title_at_start=win.title,
            max_ticks=max_ticks,
            stable_ticks_target=stable_target,
            interval=interval,
            initial_visuals=initial_visuals,
            last_visuals=initial_visuals,
            last_thumb_arr=initial_thumb,
            last_geom=geom,
            last_alpha=initial_alpha,
            smoothed_alpha=initial_alpha,
        )

        with self._lock:
            if self._active_session is not None:
                self._active_session.cancelled = True
            self._active_session = session
            self._scheduler.schedule(self.TIMER_KEY, interval, self.step_tick, session)

        return session

    def _finalize_session(
        self,
        session: ProgressiveSession,
        win: Window,
        final_visuals: WindowVisuals | None,
        captured_alpha: float,
    ) -> None:
        with self._lock:
            if self._active_session is session:
                self._active_session = None
            session.cancelled = True

        if final_visuals is None:
            return

        if session.initial_visuals is not None:
            overall_shift = visual_delta(final_visuals, session.initial_visuals)
            session.max_delta = max(session.max_delta, overall_shift)

        settle_sec = session.last_change_tick * session.interval
        updated_prof = record_class_probing_session(
            win.window_class,
            final_visuals,
            max_delta=session.max_delta,
            settle_time_sec=settle_sec,
            captured_alpha=captured_alpha,
        )
        vol_disp = updated_prof.volatility if updated_prof else session.max_delta
        settle_disp = updated_prof.settle_time if updated_prof else settle_sec
        print(
            f"[PROGRESSIVE] Settled '{win.window_class or win.address}' at tick {session.current_tick}/{session.max_ticks} "
            f"(stable={session.stable_ticks}/{session.stable_ticks_target}, max_delta={session.max_delta:.3f}, "
            f"class_vol={vol_disp:.3f}, class_settle={settle_disp:.1f}s)"
        )

    def step_tick(self, session: ProgressiveSession) -> bool:
        """
        Execute a single progressive re-evaluation tick.
        Returns True if the session remains active and scheduled the next tick, False if finished/cancelled.
        """
        if STOP_EVENT.is_set() or session.cancelled:
            return False

        with self._lock:
            if self._active_session is not session:
                return False

        win = get_hyprland_active_window()
        if win is None or win.address != session.address:
            # Focus moved away or window closed -> cancel and commit partial observation
            self.cancel(session.address, commit_partial=True)
            return False

        cfg = get_current_config()
        if is_sensitive_window(win, cfg):
            # Privacy shield: immediately force opaque, cancel progressive session without capture
            try:
                set_hyprland_win_opacity(win.address, 1.0, 1.0)
            except Exception:
                pass
            self.cancel(session.address, commit_partial=False)
            return False

        session.current_tick += 1
        try:
            captured_alpha = get_applied_alpha(win.address)
            img = capture_window(win)
        except Exception as e:
            print(f"[WARN] Progressive capture failed at tick {session.current_tick} for {win.address}: {e}")
            self.cancel(session.address, commit_partial=True)
            return False

        geom = (int(win.x), int(win.y), int(win.width), int(win.height))
        thumb = _quick_thumbnail_array(img)

        # Fast pixel-identity short-circuit: skip Sobel/quantization/IPC if pixels and geometry are identical
        if (
            session.last_thumb_arr is not None
            and thumb is not None
            and thumb.shape == session.last_thumb_arr.shape
            and geom == session.last_geom
            and int(np.max(np.abs(thumb - session.last_thumb_arr))) < 1
        ):
            session.stable_ticks += 1
            if session.stable_ticks >= session.stable_ticks_target or session.current_tick >= session.max_ticks:
                self._finalize_session(session, win, session.last_visuals, captured_alpha)
                return False

            with self._lock:
                if not session.cancelled and self._active_session is session:
                    self._scheduler.schedule(self.TIMER_KEY, session.interval, self.step_tick, session)
                    return True
            return False

        # Resolve monitor and backdrop
        mon = None
        try:
            mons = get_hyprland_monitors()
            mon = next((m for m in mons if m.id == win.monitor_id), None)
        except Exception:
            mon = None
        if mon is None:
            mon = get_hyprland_active_monitor()
        if mon is None:
            self.cancel(session.address, commit_partial=True)
            return False

        cfg = get_current_config()
        wall_path = cfg.get_wallpaper(mon.name, mon.id)
        wall_lum, wall_grad = get_cached_wallpaper_backdrop_data(wall_path, mon.width, mon.height)
        b = backdrop_behind(
            wall_lum,
            win,
            mon.x,
            mon.y,
            grad=wall_grad,
            monitor_scale=mon.scale,
        )

        class_ref = get_class_profile(win.window_class)
        visuals = window_colors(
            img,
            current_alpha=captured_alpha,
            backdrop_median=b.median,
            class_ref=class_ref,
        )

        # Safeguard: if video playback is detected, apply video_opacity and stop UI volatility probing
        is_video, _, _ = evaluate_video_score(win, visuals)
        if is_video:
            cache_put(win, visuals, captured_alpha=captured_alpha, update_class=False)
            apply_window_decision(
                win,
                visuals,
                from_cache=False,
                backdrop=b,
                monitor=mon,
                before_img_bytes=img,
                class_profile_before=class_ref,
                class_profile_after=class_ref,
            )
            self.cancel(session.address, commit_partial=False)
            return False

        if session.last_visuals is not None:
            delta = visual_delta(visuals, session.last_visuals)
        else:
            delta = 0.0
            session.initial_visuals = visuals

        geom_changed = session.last_geom is not None and geom != session.last_geom
        session.last_visuals = visuals
        session.last_thumb_arr = thumb
        session.last_geom = geom

        # Update instance cache immediately, but defer persistent class EMA update until convergence
        cache_put(win, visuals, captured_alpha=captured_alpha, update_class=False)

        # Compute raw solver alpha and apply anti-hunting temporal damping (0.60/0.40)
        # on micro-jumps (< 0.10) to eliminate 1-step boundary wobble on dynamic windows
        raw_ideal_alpha = decide_opacity(
            visuals,
            b,
            target=cfg.target_contrast,
            floor=cfg.floor_opacity,
        )
        alpha_jump = abs(raw_ideal_alpha - session.smoothed_alpha)
        if alpha_jump >= 0.10:
            # Significant shift (theme flip or real load): snap immediately with zero lag
            session.smoothed_alpha = raw_ideal_alpha
        else:
            # Micro-fluctuation (0.05 discretization hunting): damp smoothly
            session.smoothed_alpha = round(0.60 * session.smoothed_alpha + 0.40 * raw_ideal_alpha, 2)
        damped_alpha = round(session.smoothed_alpha, 2)

        # Temporal annealing: relax delta threshold slightly after initial load (t > 3)
        # to filter out residual carousel/cursor micro-noise and allow clean convergence
        effective_threshold = PROGRESSIVE_DELTA_THRESHOLD + 0.005 * max(0, min(6, session.current_tick - 3))

        if delta >= effective_threshold:
            session.stable_ticks = 0
            session.last_change_tick = session.current_tick
            session.max_delta = max(session.max_delta, delta)
            apply_window_decision(
                win,
                visuals,
                from_cache=False,
                backdrop=b,
                monitor=mon,
                before_img_bytes=img,
                class_profile_before=class_ref,
                class_profile_after=class_ref,
                target_alpha=damped_alpha,
            )
            session.last_alpha = get_applied_alpha(win.address)
        else:
            session.stable_ticks += 1
            if geom_changed:
                apply_window_decision(
                    win,
                    visuals,
                    from_cache=True,
                    backdrop=b,
                    monitor=mon,
                    before_img_bytes=img,
                    class_profile_before=class_ref,
                    class_profile_after=class_ref,
                    target_alpha=damped_alpha,
                )
                session.last_alpha = get_applied_alpha(win.address)

        if session.stable_ticks >= session.stable_ticks_target or session.current_tick >= session.max_ticks:
            self._finalize_session(session, win, visuals, session.last_alpha)
            return False

        with self._lock:
            if not session.cancelled and self._active_session is session:
                self._scheduler.schedule(self.TIMER_KEY, session.interval, self.step_tick, session)
                return True
        return False


PROGRESSIVE = ProgressiveReevaluator(SCHEDULER)


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


DECISION_LOCK = Lock()
CURRENT_ACTIVE_ADDRESS: str | None = None


def handle_event(ev: HyprEvent) -> None:
    global CURRENT_ACTIVE_ADDRESS
    if STOP_EVENT.is_set():
        return

    if ev.kind == "closewindow":
        addr = ev.content.strip().split(",")[0]
        if not addr.startswith("0x"):
            addr = f"0x{addr}"
        if CURRENT_ACTIVE_ADDRESS == addr:
            CURRENT_ACTIVE_ADDRESS = None
        PROGRESSIVE.cancel(addr, commit_partial=False)
        SCHEDULER.cancel(addr)
        cache_drop(addr)
        with MANAGED_LOCK:
            MANAGED_WINDOWS.discard(addr)
        return

    # Delays for trailing debounce
    if ev.kind == "activewindowv2":
        # Cancel any progressive session belonging to a previously focused window
        raw_addr = ev.content.strip().split(",", 1)[0].strip()
        focused_addr = raw_addr if raw_addr.startswith("0x") or not raw_addr else f"0x{raw_addr}"
        CURRENT_ACTIVE_ADDRESS = focused_addr or None
        active_sess = PROGRESSIVE.active_session
        if active_sess is not None and focused_addr and active_sess.address != focused_addr:
            PROGRESSIVE.cancel(active_sess.address, commit_partial=True)
        # Focus switch: snappy reaction, instant cache hit path
        SCHEDULER.schedule("active_window", 0.05, schedule_capture, force=False, progressive=True)
    elif ev.kind == "windowtitlev2":
        # Title changes (URL/tab change, buffer change):
        # 1. Immediately drop events for unfocused background windows
        raw_addr = ev.content.strip().split(",", 1)[0].strip()
        target_addr = raw_addr if raw_addr.startswith("0x") or not raw_addr else f"0x{raw_addr}"
        if CURRENT_ACTIVE_ADDRESS is not None and target_addr and target_addr != CURRENT_ACTIVE_ADDRESS:
            return

        # 2. Schedule debounced capture for active window without forced cache invalidation
        SCHEDULER.schedule(
            "active_window",
            0.25,
            schedule_capture,
            force=False,
            target_address=target_addr or None,
            progressive=True,
            on_title_change=True,
        )
    elif ev.kind == "openwindow":
        # New window opening: wait for window painting to settle, then start progressive re-evaluation
        SCHEDULER.schedule("active_window", 0.50, schedule_capture, force=True, progressive=True)
    elif ev.kind in ("fullscreen", "movewindowv2"):
        # Geometry changes: fast backdrop slice recalculation
        SCHEDULER.schedule("active_window", 0.08, schedule_capture, force=False, progressive=False)


def force_schedule_capture() -> None:
    schedule_capture(force=True, progressive=True)


def schedule_capture(
    force: bool = False,
    target_address: str | None = None,
    progressive: bool = False,
    on_title_change: bool = False,
) -> None:
    global CURRENT_ACTIVE_ADDRESS
    if STOP_EVENT.is_set():
        return
    win = get_hyprland_active_window()
    if win is None:
        return
    CURRENT_ACTIVE_ADDRESS = win.address
    if target_address is not None and win.address != target_address:
        # Ignore title change events emitted by unfocused background windows
        return

    cfg = get_current_config()
    if is_sensitive_window(win, cfg):
        # Privacy shield: immediately set 1.0 (opaque), skip grim capture entirely
        try:
            set_hyprland_win_opacity(win.address, 1.0, 1.0)
            record_applied_state(
                win.address,
                1.0,
                (0.0, 0.0, 0.0),
                (int(win.x), int(win.y), int(win.width), int(win.height)),
            )
        except Exception:
            pass
        PROGRESSIVE.cancel(win.address, commit_partial=False)
        return

    # On title changes for proven static windows (terminals, editors with low volatility),
    # avoid launching redundant progressive re-evaluation loops.
    if on_title_change:
        prof = get_class_profile(win.window_class)
        if prof is not None and prof.volatility < 0.025 and prof.sample_count >= 3:
            progressive = False

    if not force and (e := cache_get(win)):
        CACHE_HIT_QUEUE.put((win, e))
        if progressive:
            prof = get_class_profile(win.window_class)
            # If the window class is known to be volatile (e.g. browser), run progressive probing
            if prof is not None and prof.volatility >= 0.06:
                PROGRESSIVE.start_session(
                    win,
                    initial_visuals=e.visuals,
                    initial_alpha=get_applied_alpha(win.address),
                )
        return
    _enqueue_capture((win, progressive))


def capture_worker() -> None:
    while not STOP_EVENT.is_set():
        try:
            item = CAPTURE_QUEUE.get(timeout=1.0)
        except Empty:
            continue

        if isinstance(item, tuple):
            win, progressive = item
        else:
            win, progressive = item, False

        cfg = get_current_config()
        if is_sensitive_window(win, cfg):
            try:
                set_hyprland_win_opacity(win.address, 1.0, 1.0)
            except Exception:
                pass
            CAPTURE_QUEUE.task_done()
            continue

        try:
            # Snapshot the window's applied alpha at the exact time of screenshot capture
            alpha_at_capture = get_applied_alpha(win.address)
            img = capture_window(win)
            _enqueue_luminance((win, img, alpha_at_capture, progressive))
        except Exception as e:
            print(f"[WARN] Failed to capture window {win.address}: {e}")
        finally:
            CAPTURE_QUEUE.task_done()


def apply_window_decision(
    win: Window,
    visuals: WindowVisuals,
    from_cache: bool = False,
    backdrop: Backdrop | None = None,
    monitor: Monitor | None = None,
    is_preload: bool = False,
    before_img_bytes: bytes | None = None,
    class_profile_before: WindowVisuals | None = None,
    class_profile_after: WindowVisuals | None = None,
    target_alpha: float | None = None,
) -> None:
    with DECISION_LOCK:
        mon = monitor
        if mon is None:
            # Try matching window monitor_id
            try:
                mons = get_hyprland_monitors()
                mon = next((m for m in mons if m.id == win.monitor_id), None)
            except Exception:
                mon = None

        if mon is None:
            mon = get_hyprland_active_monitor()

        if mon is None:
            return

        cfg = get_current_config()
        wall_path = cfg.get_wallpaper(mon.name, mon.id)
        is_video, v_score, v_signals = evaluate_video_score(win, visuals)

        b = backdrop
        if b is None and (not is_video or is_dev_mode()):
            wall_lum, wall_grad = get_cached_wallpaper_backdrop_data(wall_path, mon.width, mon.height)
            b = backdrop_behind(
                wall_lum,
                win,
                mon.x,
                mon.y,
                grad=wall_grad,
                monitor_scale=mon.scale,
            )

        if is_sensitive_window(win, cfg):
            ideal_alpha = 1.0
        elif is_video:
            ideal_alpha = cfg.video_opacity
        elif target_alpha is not None:
            ideal_alpha = float(target_alpha)
        else:
            ideal_alpha = decide_opacity(
                visuals,
                b,
                target=cfg.target_contrast,
                floor=cfg.floor_opacity,
            )

        # Opacity diffing: check if current opacity is already appropriate
        with MANAGED_LOCK:
            is_already_managed = win.address in MANAGED_WINDOWS

        current_alpha = get_applied_alpha(win.address)
        alpha_diff = abs(ideal_alpha - current_alpha)
        backdrop_sig = (b.p15, b.p85, b.edge_energy) if b is not None else None
        geom = (int(win.x), int(win.y), int(win.width), int(win.height))

        dev_active = is_dev_mode()

        if is_already_managed and alpha_diff < DIFF_OPACITY_THRESHOLD:
            record_applied_state(win.address, current_alpha, backdrop_sig, geom)
            if dev_active and not is_preload and before_img_bytes is not None:
                save_dev_decision_bundle(
                    win=win,
                    mon=mon,
                    cfg=cfg,
                    wall_path=wall_path,
                    visuals=visuals,
                    backdrop=b,
                    before_alpha=current_alpha,
                    after_alpha=ideal_alpha,
                    applied_ipc=False,
                    from_cache=from_cache,
                    is_preload=is_preload,
                    is_video=is_video,
                    video_score=v_score,
                    video_signals=v_signals,
                    before_img_bytes=before_img_bytes,
                    after_img_bytes=before_img_bytes,
                    class_profile_before=class_profile_before,
                    class_profile_after=class_profile_after,
                )
            return

        # If in dev mode on a cache hit where before_img_bytes wasn't captured yet, capture before.png now
        if dev_active and before_img_bytes is None and not is_preload:
            try:
                before_img_bytes = capture_window(win)
            except Exception:
                before_img_bytes = None

        # Apply new opacity
        tag = "[PRELOAD]" if is_preload else "[DECIDE]"
        if is_video:
            prefix = " (cache hit - VIDEO)" if from_cache else " (VIDEO DETECTED)"
            print(f"{tag}{prefix} alpha: {ideal_alpha:.2f} (S={v_score:.2f}) for {win.address}")
        else:
            prefix = " (cache hit) " if from_cache else " "
            print(
                f"{tag}{prefix}alpha: {ideal_alpha:.2f} "
                f"(text_dens={visuals.text_density:.2f}, bg_ratio={visuals.bg_ratio:.2f}, wall_edge={b.edge_energy:.3f}) "
                f"for {win.address}"
            )

        set_hyprland_win_opacity(win.address, ideal_alpha, ideal_alpha)
        record_applied_state(win.address, ideal_alpha, backdrop_sig, geom)
        record_managed_window(win.address)

        if dev_active and not is_preload:
            after_img_bytes: bytes | None = None
            try:
                # Allow compositor to render the newly dispatched opacity before capturing after.png
                time.sleep(0.08)
                after_img_bytes = capture_window(win)
            except Exception as e:
                print(f"[WARN] Failed to capture after.png for {win.address}: {e}")

            if class_profile_before is None and win.window_class:
                class_profile_before = get_class_profile(win.window_class)
            if class_profile_after is None and win.window_class:
                class_profile_after = get_class_profile(win.window_class)

            save_dev_decision_bundle(
                win=win,
                mon=mon,
                cfg=cfg,
                wall_path=wall_path,
                visuals=visuals,
                backdrop=b,
                before_alpha=current_alpha,
                after_alpha=ideal_alpha,
                applied_ipc=True,
                from_cache=from_cache,
                is_preload=is_preload,
                is_video=is_video,
                video_score=v_score,
                video_signals=v_signals,
                before_img_bytes=before_img_bytes,
                after_img_bytes=after_img_bytes,
                class_profile_before=class_profile_before,
                class_profile_after=class_profile_after,
            )


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
            item = LUMINANCE_QUEUE.get(timeout=1.0)
        except Empty:
            continue

        try:
            progressive = False
            if len(item) == 4:
                win, img, captured_alpha, progressive = item
            elif len(item) == 3:
                win, img, captured_alpha = item
            else:
                win, img = item
                captured_alpha = get_applied_alpha(win.address)

            mon = None
            try:
                mons = get_hyprland_monitors()
                mon = next((m for m in mons if m.id == win.monitor_id), None)
            except Exception:
                mon = None
            if mon is None:
                mon = get_hyprland_active_monitor()
            if mon is None:
                continue

            cfg = get_current_config()
            wall_path = cfg.get_wallpaper(mon.name, mon.id)
            wall_lum, wall_grad = get_cached_wallpaper_backdrop_data(wall_path, mon.width, mon.height)
            b = backdrop_behind(
                wall_lum,
                win,
                mon.x,
                mon.y,
                grad=wall_grad,
                monitor_scale=mon.scale,
            )

            class_ref = get_class_profile(win.window_class)

            # Optical unblending using the exact alpha active when the screenshot was captured
            visuals = window_colors(
                img,
                current_alpha=captured_alpha,
                backdrop_median=b.median,
                class_ref=class_ref,
            )

            # If starting a progressive re-evaluation session, only seed class profile if none exists yet;
            # otherwise wait for progressive convergence to update the persistent class EMA.
            use_progressive = bool(progressive and cfg.reeval_max_ticks > 0)
            should_update_class_now = (not use_progressive) or (class_ref is None)
            cache_put(win, visuals, captured_alpha=captured_alpha, update_class=should_update_class_now)
            updated_class_ref = get_class_profile(win.window_class)
            apply_window_decision(
                win,
                visuals,
                from_cache=False,
                backdrop=b,
                monitor=mon,
                before_img_bytes=img,
                class_profile_before=class_ref,
                class_profile_after=updated_class_ref,
            )
            if use_progressive:
                is_video, _, _ = evaluate_video_score(win, visuals)
                if not is_video:
                    PROGRESSIVE.start_session(
                        win,
                        initial_visuals=visuals,
                        initial_thumb=_quick_thumbnail_array(img),
                        initial_alpha=get_applied_alpha(win.address),
                    )
        except Exception as e:
            print(f"[WARN] Error in luminance_worker: {e}")
        finally:
            LUMINANCE_QUEUE.task_done()


def preload_all_windows() -> None:
    """Preload and apply opacity to all mapped windows using cached window/class profiles."""
    if STOP_EVENT.is_set():
        return
    try:
        # Get all mapped, non-hidden windows across all workspaces and monitors
        all_windows = get_hyprland_windows(filter_fn=lambda w: not w.get("hidden", False) and w.get("mapped", False))
        if not all_windows:
            return

        mons = {m.id: m for m in get_hyprland_monitors()}
        count_preloaded = 0

        cfg = get_current_config()
        for win in all_windows:
            if STOP_EVENT.is_set():
                break
            if is_sensitive_window(win, cfg):
                try:
                    set_hyprland_win_opacity(win.address, 1.0, 1.0)
                    record_applied_state(
                        win.address,
                        1.0,
                        (0.0, 0.0, 0.0),
                        (int(win.x), int(win.y), int(win.width), int(win.height)),
                    )
                    count_preloaded += 1
                except Exception:
                    pass
                continue

            cached = cache_get(win)
            profile = cached.visuals if cached is not None else get_class_profile(win.window_class)
            if profile is None:
                continue

            mon = mons.get(win.monitor_id)
            apply_window_decision(win, profile, from_cache=True, monitor=mon, is_preload=True)
            count_preloaded += 1

        if count_preloaded > 0:
            print(f"[INFO] Applied decisions to {count_preloaded} window(s) across workspaces")
    except Exception as e:
        print(f"[WARN] Error during window profile preloading: {e}")


def config_watcher_worker() -> None:
    """Watch config.yaml for live edits and re-evaluate all open windows when settings change."""
    from hyprsmart.config import CONFIG_FILE, load_config

    try:
        last_mtime = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else None
    except OSError:
        last_mtime = None

    while not STOP_EVENT.is_set():
        time.sleep(0.5)
        try:
            if CONFIG_FILE.exists():
                mtime = CONFIG_FILE.stat().st_mtime
                if last_mtime is not None and mtime != last_mtime:
                    last_mtime = mtime
                    cfg = load_config()
                    print(
                        f"[INFO] Reloaded config.yaml "
                        f"(target_contrast={cfg.target_contrast}, floor_opacity={cfg.floor_opacity}, "
                        f"video_opacity={cfg.video_opacity}, reeval_max_ticks={cfg.reeval_max_ticks}, "
                        f"reeval_stable_ticks={cfg.reeval_stable_ticks})"
                    )
                    preload_all_windows()
                    force_schedule_capture()
                elif last_mtime is None:
                    last_mtime = mtime
        except Exception as e:
            print(f"[WARN] Error in config_watcher_worker: {e}")


def load_hyprsmart_daemons() -> None:
    STOP_EVENT.clear()
    Thread(target=capture_worker, daemon=True).start()
    Thread(target=cache_hit_worker, daemon=True).start()
    Thread(target=luminance_worker, daemon=True).start()
    Thread(target=config_watcher_worker, daemon=True).start()
    print("[INFO] Started HyprSmart workers")
    # Preload profiles for all existing windows immediately
    Thread(target=preload_all_windows, daemon=True).start()
    SCHEDULER.schedule("initial_startup", 0.5, schedule_capture, force=False, progressive=True)


def stop_hyprsmart_daemons() -> None:
    STOP_EVENT.set()
    PROGRESSIVE.cancel(commit_partial=False)
    SCHEDULER.cancel_all()
    restore_all_managed_windows()

