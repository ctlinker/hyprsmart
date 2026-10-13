import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from hyprsmart.config import (
    CONFIG_FILE,
    get_current_config,
    load_config,
    set_monitor_wallpaper,
)
from hyprsmart.daemon import (
    ControlServer,
    cache_clear,
    force_schedule_capture,
    get_control_socket_path,
    get_pid_file_path,
    handle_event,
    listen_hyprland_socket,
    load_hyprsmart_daemons,
    restore_all_managed_windows,
    send_control_command,
    stop_hyprsmart_daemons,
)
from hyprsmart.opacity import clear_wallpaper_cache
from hyprsmart.primitive import get_hyprland_monitors


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


def run_daemon_loop() -> None:
    """Run the HyprSmart daemon in the foreground."""
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
                "config": {
                    "monitors": cfg.monitors,
                    "default_wallpaper": cfg.default_wallpaper,
                    "target_contrast": cfg.target_contrast,
                    "floor_opacity": cfg.floor_opacity,
                },
            }
        elif cmd == "reload":
            print("[INFO] Reload request received")
            load_config()
            clear_wallpaper_cache()
            cache_clear()
            force_schedule_capture()
            return {"status": "ok", "message": "Configuration and caches reloaded"}
        elif cmd == "set_monitor_wall":
            mon = req.get("monitor")
            wall = req.get("wallpaper")
            if mon and wall:
                set_monitor_wallpaper(mon, wall)
                clear_wallpaper_cache()
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
    running_pid = is_daemon_running()
    if running_pid:
        print(f"[INFO] HyprSmart is already running (PID {running_pid}).")
        return

    if args.foreground:
        run_daemon_loop()
    else:
        log_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hyprsmart"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(log_dir / "hyprsmart.log", "a")

        proc = subprocess.Popen(
            [sys.executable, "-m", "hyprsmart", "start", "--foreground"],
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
        # Give it a moment to initialize
        time.sleep(0.3)
        print(f"[OK] HyprSmart daemon started in background (PID {proc.pid}).")
        print(f"[INFO] Logs written to {log_dir / 'hyprsmart.log'}")


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
    try:
        res = send_control_command({"cmd": "reload"}, timeout=2.0)
        print(f"[OK] {res.get('message', 'Reloaded successfully.')}")
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
        except Exception:
            print("Control Socket: unresponsive")
    else:
        print("Status: STOPPED")

    print(f"Config File: {CONFIG_FILE}")
    print(f"Target Contrast: {cfg.target_contrast}")
    print(f"Floor Opacity: {cfg.floor_opacity}")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hyprsmart",
        description="HyprSmart: Dynamic accessibility & transparency daemon for Hyprland",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # start
    p_start = subparsers.add_parser("start", help="Start the HyprSmart daemon")
    p_start.add_argument(
        "-f", "--foreground",
        action="store_true",
        help="Run daemon in the foreground (do not detach)",
    )

    # stop
    subparsers.add_parser("stop", help="Stop the running HyprSmart daemon")

    # reload
    subparsers.add_parser("reload", help="Reload configuration and wallpaper caches")

    # status
    subparsers.add_parser("status", help="Show daemon status and monitor configuration")

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

    return parser


def main() -> None:
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
    elif args.subcommand == "monitor":
        cmd_monitor(args)
    else:
        # If no arguments provided, display status or help
        parser.print_help()
