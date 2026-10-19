from dataclasses import dataclass
from collections.abc import Callable
import os
import socket
import threading
import time

@dataclass
class HyprEvent:
    kind: str
    content: str


def get_hyprland_event_socket_path() -> str | None:
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    his = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not xdg_runtime or not his:
        return None
    return os.path.join(xdg_runtime, "hypr", his, ".socket2.sock")


def get_hyprland_command_socket_path() -> str | None:
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    his = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not xdg_runtime or not his:
        return None
    return os.path.join(xdg_runtime, "hypr", his, ".socket.sock")


def listen_hyprland_socket(
    handle: Callable[[HyprEvent], None],
    stop_event: threading.Event | None = None,
) -> None:
    """
    Connect to Hyprland's .socket2.sock and forward events to handle callback.
    Includes auto-reconnect logic if Hyprland reloads or disconnects.
    """
    while stop_event is None or not stop_event.is_set():
        socket_path = get_hyprland_event_socket_path()
        if not socket_path or not os.path.exists(socket_path):
            print("[WARN] Hyprland event socket not found. Retrying in 1s...")
            time.sleep(1.0)
            continue

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(socket_path)
                sock.settimeout(1.0)
                print(f"[INFO] Connected to Hyprland event socket: {socket_path}")

                buffer = b""
                while stop_event is None or not stop_event.is_set():
                    try:
                        chunk = sock.recv(4096)
                        if not chunk:
                            print("[WARN] Hyprland event socket connection closed by server.")
                            break
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            line_str = line.decode("utf-8", errors="replace").strip()
                            if ">>" not in line_str:
                                continue
                            kind, content = line_str.split(">>", 1)
                            handle(HyprEvent(kind.strip(), content.strip()))
                    except socket.timeout:
                        continue
                    except Exception as e:
                        if stop_event and stop_event.is_set():
                            break
                        print(f"[WARN] Error reading from Hyprland socket: {e}")
                        break
        except Exception as e:
            if stop_event and stop_event.is_set():
                break
            print(f"[WARN] Failed to connect to Hyprland socket ({e}). Reconnecting in 1s...")
            time.sleep(1.0)
