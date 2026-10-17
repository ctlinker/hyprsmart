import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

from hyprsmart.config import (
    BLACKLIST_FILE,
    CONFIG_FILE,
    SETTINGS_METADATA,
    SYSTEM_BLACKLIST_FILE,
    get_blacklist_info,
    get_blacklist_path,
    get_current_config,
    load_blacklist,
    load_config,
    save_blacklist,
    set_monitor_wallpaper,
    update_setting,
)
from hyprsmart.daemon import (
    ControlServer,
    cache_clear,
    force_schedule_capture,
    get_control_socket_path,
    get_dev_captures_dir,
    get_pid_file_path,
    handle_event,
    is_dev_mode,
    listen_hyprland_socket,
    load_hyprsmart_daemons,
    preload_all_windows,
    restore_all_managed_windows,
    save_dev_decision_bundle,
    send_control_command,
    set_dev_mode,
    stop_hyprsmart_daemons,
)
from hyprsmart.daemon.cache import (
    cache_put,
    get_applied_alpha,
    get_class_profile,
    record_applied_state,
)
from hyprsmart.opacity import (
    backdrop_behind,
    clear_wallpaper_cache,
    decide_opacity,
    evaluate_video_score,
    get_cached_wallpaper_backdrop_data,
    window_colors,
)
from hyprsmart.primitive import (
    capture_window,
    get_hyprland_active_monitor,
    get_hyprland_active_window,
    get_hyprland_monitors,
    set_hyprland_win_opacity,
)

DEV_FLAG_NAME = "--yes-am-a-dev-on-this-project-and-i-fully-understand-what-this-flag-does"


def get_log_file_path() -> Path:
    log_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hyprsmart"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "hyprsmart.log"


def is_daemon_running() -> int | None:
    """Check if the daemon is currently running, returning its PID if active."""
    pid_file = get_pid_file_path()
    if not pid_file.exists():
        return None

    try:
        pid = int(pid_file.read_text().strip())
        # Check if process is alive
        os.kill(pid, 0)
        return pid
    except (ValueError, OSError):
        # Process dead or stale PID file
        try:
            pid_file.unlink()
        except OSError:
            pass
        return None


def run_oneshot_dev_capture() -> Path | None:
    """Capture the active window right now, run a decision, and save before.png, after.png, and metadata.json."""
    cfg = load_config()
    win = get_hyprland_active_window()
    if win is None:
        print("[WARN] No active Hyprland window found to capture.")
        return None

    mon = None
    try:
        mons = get_hyprland_monitors()
        mon = next((m for m in mons if m.id == win.monitor_id), None)
    except Exception:
        mon = None
    if mon is None:
        mon = get_hyprland_active_monitor()
    if mon is None:
        print("[WARN] No active Hyprland monitor found.")
        return None

    current_alpha = get_applied_alpha(win.address)
    before_bytes = capture_window(win)
    wall_path = cfg.get_wallpaper(mon.name, mon.id)
    wall_lum, wall_grad = get_cached_wallpaper_backdrop_data(wall_path, mon.width, mon.height)
    b = backdrop_behind(wall_lum, win, mon.x, mon.y, grad=wall_grad, monitor_scale=mon.scale)

    class_ref_before = get_class_profile(win.window_class)
    visuals = window_colors(
        before_bytes,
        current_alpha=current_alpha,
        backdrop_median=b.median,
        class_ref=class_ref_before,
    )
    cache_put(win, visuals, captured_alpha=current_alpha)
    class_ref_after = get_class_profile(win.window_class)

    is_video, v_score, v_signals = evaluate_video_score(win, visuals)
    if is_video:
        ideal_alpha = cfg.video_opacity
    else:
        ideal_alpha = decide_opacity(
            visuals,
            b,
            target=cfg.target_contrast,
            floor=cfg.floor_opacity,
        )

    set_hyprland_win_opacity(win.address, ideal_alpha, ideal_alpha)
    record_applied_state(
        win.address,
        ideal_alpha,
        (b.p15, b.p85, b.edge_energy),
        (int(win.x), int(win.y), int(win.width), int(win.height)),
    )
    time.sleep(0.08)
    after_bytes = capture_window(win)

    return save_dev_decision_bundle(
        win=win,
        mon=mon,
        cfg=cfg,
        wall_path=wall_path,
        visuals=visuals,
        backdrop=b,
        before_alpha=current_alpha,
        after_alpha=ideal_alpha,
        applied_ipc=True,
        from_cache=False,
        is_preload=False,
        is_video=is_video,
        video_score=v_score,
        video_signals=v_signals,
        before_img_bytes=before_bytes,
        after_img_bytes=after_bytes,
        class_profile_before=class_ref_before,
        class_profile_after=class_ref_after,
    )


def run_daemon_loop(dev_trace: bool = False) -> None:
    """Run the HyprSmart daemon in the foreground."""
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    set_dev_mode(dev_trace)
    if dev_trace:
        print(f"[INFO] Developer trace mode ENABLED ({DEV_FLAG_NAME})")
        print(f"[INFO] Saving before.png, after.png, metadata.json to {get_dev_captures_dir()}")

    pid = os.getpid()
    pid_file = get_pid_file_path()
    pid_file.write_text(str(pid))

    stop_event = threading.Event()

    def handle_control_request(req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd == "ping":
            return {"status": "ok", "message": "pong"}
        elif cmd == "status":
            cfg = get_current_config()
            return {
                "status": "ok",
                "pid": pid,
                "dev_trace": is_dev_mode(),
                "dev_captures_dir": str(get_dev_captures_dir()),
                "config": {
                    "monitors": cfg.monitors,
                    "default_wallpaper": cfg.default_wallpaper,
                    "target_contrast": cfg.target_contrast,
                    "floor_opacity": cfg.floor_opacity,
                    "video_opacity": cfg.video_opacity,
                    "debounce_interval": cfg.debounce_interval,
                    "reeval_max_ticks": cfg.reeval_max_ticks,
                    "reeval_stable_ticks": cfg.reeval_stable_ticks,
                    "reeval_interval": cfg.reeval_interval,
                },
            }
        elif cmd == "set_dev_mode":
            enabled = bool(req.get("enabled", True))
            set_dev_mode(enabled)
            state_str = "ENABLED" if enabled else "DISABLED"
            print(f"[INFO] Developer trace mode {state_str} via control socket")
            if enabled:
                force_schedule_capture()
            return {
                "status": "ok",
                "message": f"Developer trace mode {state_str} (dir: {get_dev_captures_dir()})",
                "dev_captures_dir": str(get_dev_captures_dir()),
            }
        elif cmd == "reload":
            print("[INFO] Reload request received")
            if "dev_trace" in req:
                set_dev_mode(bool(req["dev_trace"]))
            load_config()
            clear_wallpaper_cache()
            cache_clear()
            preload_all_windows()
            force_schedule_capture()
            return {"status": "ok", "message": "Configuration and caches reloaded"}
        elif cmd == "set_setting":
            key = req.get("key")
            value = req.get("value")
            if not key or value is None:
                return {"status": "error", "message": "Missing key or value parameter"}
            ok, msg, _ = update_setting(key, str(value))
            if ok:
                preload_all_windows()
                force_schedule_capture()
                return {"status": "ok", "message": msg}
            return {"status": "error", "message": msg}
        elif cmd == "set_monitor_wall":
            mon = req.get("monitor")
            wall = req.get("wallpaper")
            if mon and wall:
                set_monitor_wallpaper(mon, wall)
                clear_wallpaper_cache()
                preload_all_windows()
                force_schedule_capture()
                return {"status": "ok", "message": f"Monitor {mon} wallpaper updated"}
            return {"status": "error", "message": "Missing monitor or wallpaper parameter"}
        elif cmd == "stop":
            print("[INFO] Stop request received via control socket")
            threading.Thread(target=cleanup_and_exit, args=(0,)).start()
            return {"status": "ok", "message": "Stopping daemon"}
        return {"status": "error", "message": f"Unknown command: {cmd}"}

    control_server = ControlServer(handle_control_request)
    control_server.start()

    def cleanup_and_exit(signum: int = 0, frame=None) -> None:
        print("\n[INFO] Shutting down HyprSmart daemon...")
        stop_event.set()
        control_server.stop()
        stop_hyprsmart_daemons()
        try:
            if pid_file.exists():
                pid_file.unlink()
        except OSError:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup_and_exit)
    signal.signal(signal.SIGTERM, cleanup_and_exit)

    load_config()
    load_hyprsmart_daemons()

    print(f"[INFO] HyprSmart daemon started (PID {pid})")
    try:
        listen_hyprland_socket(handle_event, stop_event=stop_event)
    except KeyboardInterrupt:
        cleanup_and_exit()


def cmd_start(args: argparse.Namespace) -> None:
    dev_flag = bool(getattr(args, "dev_trace", False) or getattr(args, "root_dev_trace", False))
    running_pid = is_daemon_running()
    if running_pid:
        if dev_flag:
            try:
                res = send_control_command({"cmd": "set_dev_mode", "enabled": True}, timeout=2.0)
                print(f"[OK] {res.get('message', 'Enabled dev trace mode on running daemon.')}")
            except Exception as e:
                print(f"[WARN] Daemon is running (PID {running_pid}) but failed to enable dev mode: {e}")
        else:
            print(f"[INFO] HyprSmart is already running (PID {running_pid}).")
        return

    if args.foreground:
        run_daemon_loop(dev_trace=dev_flag)
    else:
        log_path = get_log_file_path()
        log_file = open(log_path, "a", encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        cmd = [sys.executable, "-m", "hyprsmart", "start", "--foreground"]
        if dev_flag:
            cmd.append(DEV_FLAG_NAME)

        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            env=env,
            start_new_session=True,
        )
        # Give it a moment to initialize
        time.sleep(0.3)
        print(f"[OK] HyprSmart daemon started in background (PID {proc.pid}).")
        print(f"[INFO] Logs written to {log_path}")
        if dev_flag:
            print(f"[INFO] Dev trace bundles (before.png, after.png, metadata.json) -> {get_dev_captures_dir()}")


def cmd_stop(args: argparse.Namespace) -> None:
    running_pid = is_daemon_running()
    if not running_pid:
        print("[INFO] HyprSmart daemon is not running.")
        return

    try:
        res = send_control_command({"cmd": "stop"}, timeout=2.0)
        print(f"[OK] Daemon stopping: {res.get('message', 'done')}")
    except Exception:
        # Fallback to direct SIGTERM
        try:
            os.kill(running_pid, signal.SIGTERM)
            print(f"[OK] Sent SIGTERM to daemon PID {running_pid}.")
        except OSError as e:
            print(f"[WARN] Failed to terminate PID {running_pid}: {e}")

    # Wait up to 2 seconds for process to exit
    for _ in range(20):
        if not is_daemon_running():
            break
        time.sleep(0.1)

    print("[OK] HyprSmart daemon stopped.")


def cmd_reload(args: argparse.Namespace) -> None:
    dev_flag = bool(getattr(args, "dev_trace", False) or getattr(args, "root_dev_trace", False))
    try:
        payload: dict = {"cmd": "reload"}
        if dev_flag:
            payload["dev_trace"] = True
        res = send_control_command(payload, timeout=2.0)
        print(f"[OK] {res.get('message', 'Reloaded successfully.')}")
        if dev_flag:
            print(f"[INFO] Dev trace bundles enabled -> {get_dev_captures_dir()}")
    except ConnectionRefusedError:
        print("[WARN] Daemon is not running. Reloaded local config only.")
        load_config()


def cmd_monitor(args: argparse.Namespace) -> None:
    mon_id = args.id
    wall = args.use_wall

    resolved_path = Path(wall).expanduser().resolve()
    if not resolved_path.exists():
        print(f"[WARN] Wallpaper file does not exist: {resolved_path}")

    set_monitor_wallpaper(mon_id, str(resolved_path))
    print(f"[OK] Saved wallpaper for monitor '{mon_id}': {resolved_path}")

    # If daemon is running, notify it
    try:
        send_control_command({
            "cmd": "set_monitor_wall",
            "monitor": mon_id,
            "wallpaper": str(resolved_path),
        }, timeout=2.0)
        print("[OK] Notified running daemon of wallpaper change.")
    except Exception:
        pass


def cmd_status(args: argparse.Namespace) -> None:
    running_pid = is_daemon_running()
    cfg = load_config()

    print("=== HyprSmart Status ===")
    if running_pid:
        print(f"Status: RUNNING (PID {running_pid})")
        try:
            res = send_control_command({"cmd": "status"}, timeout=1.5)
            socket_path = get_control_socket_path()
            print(f"Control Socket: {socket_path}")
            if res.get("dev_trace"):
                print(f"Dev Trace Mode: ENABLED ({res.get('dev_captures_dir')})")
            else:
                print("Dev Trace Mode: DISABLED")
        except Exception:
            print("Control Socket: unresponsive")
    else:
        print("Status: STOPPED")

    print(f"Config File: {CONFIG_FILE}")
    print(f"Target Contrast: {cfg.target_contrast}")
    print(f"Floor Opacity: {cfg.floor_opacity}")
    print(f"Video Opacity: {cfg.video_opacity}")
    print(f"Default Wallpaper: {cfg.default_wallpaper or 'None'}")

    print("\nConnected Monitors (Hyprland):")
    try:
        monitors = get_hyprland_monitors()
        if not monitors:
            print("  (None detected)")
        for m in monitors:
            configured_wall = cfg.get_wallpaper(m.name, m.id)
            print(f"  • ID {m.id} | Name: {m.name} | Res: {m.width}x{m.height} | Scale: {m.scale}")
            print(f"    Wallpaper: {configured_wall or 'None (using fallback)'}")
    except Exception as e:
        print(f"  (Failed to query Hyprland: {e})")

    if cfg.monitors:
        print("\nConfigured Wallpapers Mapping:")
        for mon_key, wall_val in cfg.monitors.items():
            print(f"  - Monitor '{mon_key}': {wall_val}")


def cmd_what_is_it_doing(args: argparse.Namespace) -> None:
    log_path = get_log_file_path()
    lines_to_show = max(1, args.lines)

    if not log_path.exists():
        if not args.watch:
            print(f"[INFO] No logs found at {log_path}. (Start the daemon with 'hyprsmart start')")
            return
        print(f"[INFO] Waiting for logs to appear at {log_path}... (Press Ctrl+C to stop)")
        try:
            while not log_path.exists():
                time.sleep(0.5)
        except KeyboardInterrupt:
            return

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            # Read existing lines
            all_lines = f.readlines()
            for line in all_lines[-lines_to_show:]:
                sys.stdout.write(line)
            sys.stdout.flush()

            if not args.watch:
                return

            # Follow mode (tail -f)
            while True:
                line = f.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    time.sleep(0.1)
    except KeyboardInterrupt:
        pass


def cmd_settings(args: argparse.Namespace) -> None:
    cfg = load_config()

    if not args.key:
        print("=== HyprSmart Settings ===")
        for key, meta in SETTINGS_METADATA.items():
            curr_val = getattr(cfg, key, None)
            val_display = str(curr_val) if curr_val is not None else "None"
            print(f"  • {key} = {val_display}")
            print(f"    {meta['description']}")
        print("\nTo update a setting: hyprsmart settings <key> <value>")
        return

    key = args.key
    if args.value is None:
        meta = SETTINGS_METADATA.get(key)
        if meta is None:
            valid_keys = ", ".join(SETTINGS_METADATA.keys())
            print(f"[ERROR] Unknown setting '{key}'. Valid options: {valid_keys}")
            return
        curr_val = getattr(cfg, key, None)
        print(f"{key} = {curr_val}")
        print(f"Description: {meta['description']}")
        return

    # Update setting
    val = args.value
    ok, msg, new_cfg = update_setting(key, val)
    if not ok:
        print(f"[ERROR] {msg}")
        return

    print(f"[OK] {msg}")

    # Notify daemon if running
    try:
        res = send_control_command({"cmd": "set_setting", "key": key, "value": val}, timeout=2.0)
        if res.get("status") == "ok":
            print("[OK] Notified running daemon of setting change.")
        else:
            print(f"[WARN] Daemon returned: {res.get('message')}")
    except ConnectionRefusedError:
        pass
    except Exception as e:
        print(f"[WARN] Failed to notify daemon: {e}")


def _notify_daemon_reload() -> None:
    try:
        res = send_control_command({"cmd": "reload"}, timeout=2.0)
        if res.get("status") == "ok":
            print("[OK] Notified running daemon: privacy shield configuration reloaded.")
    except ConnectionRefusedError:
        pass
    except Exception as e:
        print(f"[WARN] Failed to notify daemon: {e}")


def cmd_blacklist(args: argparse.Namespace) -> None:
    action = getattr(args, "blacklist_action", None)
    if action in (None, "list"):
        info = get_blacklist_info()
        print("=== HyprSmart Privacy Shield Blacklist ===")
        print(f"Path: {info['path']}")
        print(f"Status: {'Active' if info['exists'] else 'Default (in-memory)'}")
        perm_desc = "read-only" if info["is_readonly"] else "writable"
        print(f"Permissions: {info['mode']} ({perm_desc})")
        print(f"Owner: {info['owner']}")
        tool_str = info['escalation_tool'] or "None detected (pkexec/sudo)"
        print(f"Privilege Escalation Tool: {tool_str}")
        print()
        classes = sorted(info["classes"])
        print(f"Shielded Window Classes ({len(classes)}):")
        for c in classes:
            print(f"  • {c}")
        print()
        print("Shielded Title Keywords (always active):")
        for kw in info["keywords"]:
            print(f"  • {kw}")
        print()
        print("To modify the blacklist, run:")
        print("  hyprsmart blacklist add <class_name>")
        print("  hyprsmart blacklist remove <class_name>")
        print("  hyprsmart blacklist lock [--system]")
        return

    if action == "add":
        classes_to_add = args.classes
        CLASS_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
        for c in classes_to_add:
            if not CLASS_NAME_RE.match(c):
                print(f"[ERROR] Invalid window class name '{c}'. Only alphanumeric, '_', '-', and '.' are allowed.")
                return

        current_classes = load_blacklist()
        added = []
        for c in classes_to_add:
            c_clean = c.strip().lower()
            if c_clean not in current_classes:
                current_classes.append(c_clean)
                added.append(c_clean)

        if not added:
            print("[INFO] All specified classes are already present in the blacklist.")
            return

        ok, msg = save_blacklist(current_classes)
        if not ok:
            print(f"[ERROR] Failed to update blacklist: {msg}")
            sys.exit(1)

        print(f"[OK] Added to blacklist: {', '.join(added)}")
        _notify_daemon_reload()

    elif action == "remove":
        classes_to_remove = [c.strip().lower() for c in args.classes]
        current_classes = load_blacklist()
        removed = []
        for c in classes_to_remove:
            if c in current_classes:
                current_classes.remove(c)
                removed.append(c)

        if not removed:
            print("[INFO] None of the specified classes were found in the blacklist.")
            return

        ok, msg = save_blacklist(current_classes)
        if not ok:
            print(f"[ERROR] Failed to update blacklist: {msg}")
            sys.exit(1)

        print(f"[OK] Removed from blacklist: {', '.join(removed)}")
        _notify_daemon_reload()

    elif action == "lock":
        if args.system:
            target = SYSTEM_BLACKLIST_FILE
            classes = load_blacklist()
            ok, msg = save_blacklist(classes, target_path=target)
            if not ok:
                print(f"[ERROR] Failed to lock blacklist to {target}: {msg}")
                sys.exit(1)
            print(f"[OK] Blacklist promoted and locked at system path: {target} (read-only 0444).")
        else:
            path = get_blacklist_path()
            classes = load_blacklist()
            ok, msg = save_blacklist(classes, target_path=path)
            if not ok:
                print(f"[ERROR] Failed to lock blacklist at {path}: {msg}")
                sys.exit(1)
            print(f"[OK] Blacklist locked at: {path} (read-only 0444).")
        _notify_daemon_reload()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hyprsmart",
        description="HyprSmart: Dynamic accessibility & transparency daemon for Hyprland",
    )
    parser.add_argument(
        DEV_FLAG_NAME,
        dest="root_dev_trace",
        action="store_true",
        help="Developer diagnostic mode: save before.png, after.png, and metadata.json for opacity decisions",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # start
    p_start = subparsers.add_parser("start", help="Start the HyprSmart daemon")
    p_start.add_argument(
        "-f", "--foreground",
        action="store_true",
        help="Run daemon in the foreground (do not detach)",
    )
    p_start.add_argument(
        DEV_FLAG_NAME,
        dest="dev_trace",
        action="store_true",
        help="Save before.png, after.png, and metadata.json for every opacity decision",
    )

    # stop
    subparsers.add_parser("stop", help="Stop the running HyprSmart daemon")

    # reload
    p_reload = subparsers.add_parser("reload", help="Reload configuration and wallpaper caches")
    p_reload.add_argument(
        DEV_FLAG_NAME,
        dest="dev_trace",
        action="store_true",
        help="Enable developer decision tracing on reload",
    )

    # status
    subparsers.add_parser("status", help="Show daemon status and monitor configuration")

    # what-is-it-doing
    p_what = subparsers.add_parser(
        "what-is-it-doing",
        help="Echo daemon logs to the console",
    )
    p_what.add_argument(
        "-w", "--watch",
        action="store_true",
        help="Keep watching and streaming logs in real time (like tail -f)",
    )
    p_what.add_argument(
        "-n", "--lines",
        type=int,
        default=50,
        help="Number of initial lines to display (default: 50)",
    )

    # monitor
    p_mon = subparsers.add_parser("monitor", help="Configure wallpaper for a monitor")
    p_mon.add_argument(
        "--id",
        required=True,
        help="Monitor ID (e.g. 0) or name (e.g. eDP-1)",
    )
    p_mon.add_argument(
        "--use-wall",
        required=True,
        help="Path to the wallpaper image to use for this monitor",
    )

    # settings
    p_set = subparsers.add_parser(
        "settings",
        help="View or modify daemon configuration settings",
    )
    p_set.add_argument(
        "key",
        nargs="?",
        default=None,
        help="Setting key name (e.g. video_opacity)",
    )
    p_set.add_argument(
        "value",
        nargs="?",
        default=None,
        help="New value for the setting",
    )

    # blacklist
    p_bl = subparsers.add_parser(
        "blacklist",
        help="Manage privacy-shielded window classes in read-only blacklist.yaml",
    )
    bl_sub = p_bl.add_subparsers(dest="blacklist_action", help="Blacklist actions")

    # blacklist list
    bl_sub.add_parser("list", help="List shielded window classes and security status")

    # blacklist add
    p_bl_add = bl_sub.add_parser("add", help="Add window class(es) to read-only blacklist")
    p_bl_add.add_argument("classes", nargs="+", help="Window class name(s) to shield (e.g. keepassxc)")

    # blacklist remove
    p_bl_remove = bl_sub.add_parser("remove", help="Remove window class(es) from blacklist")
    p_bl_remove.add_argument("classes", nargs="+", help="Window class name(s) to unshield")

    # blacklist lock
    p_bl_lock = bl_sub.add_parser("lock", help="Enforce 0444 read-only permissions on blacklist")
    p_bl_lock.add_argument(
        "--system",
        action="store_true",
        help="Promote and lock blacklist to /etc/hyprsmart/blacklist.yaml (root-protected)",
    )

    return parser


def main() -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("[ERROR] Running HyprSmart as root/superuser is strictly disallowed for security reasons.", file=sys.stderr)
        sys.exit(1)

    parser = build_parser()
    args = parser.parse_args()

    if args.subcommand == "start":
        cmd_start(args)
    elif args.subcommand == "stop":
        cmd_stop(args)
    elif args.subcommand == "reload":
        cmd_reload(args)
    elif args.subcommand == "status":
        cmd_status(args)
    elif args.subcommand == "what-is-it-doing":
        cmd_what_is_it_doing(args)
    elif args.subcommand == "monitor":
        cmd_monitor(args)
    elif args.subcommand == "settings":
        cmd_settings(args)
    elif args.subcommand == "blacklist":
        cmd_blacklist(args)
    elif getattr(args, "root_dev_trace", False):
        # Invoked directly as `hyprsmart --yes-am-a-dev-on-this-project-and-i-fully-understand-what-this-flag-does`
        running_pid = is_daemon_running()
        if running_pid:
            try:
                res = send_control_command({"cmd": "set_dev_mode", "enabled": True}, timeout=2.0)
                print(f"[OK] {res.get('message', 'Enabled dev trace mode on running daemon.')}")
            except Exception as e:
                print(f"[WARN] Could not toggle running daemon via control socket: {e}")
        bundle = run_oneshot_dev_capture()
        if bundle:
            print(f"[OK] Saved immediate diagnostic snapshot to: {bundle}")
    else:
        # If no arguments provided, display status or help
        parser.print_help()
