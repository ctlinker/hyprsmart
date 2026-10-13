from dataclasses import dataclass
from collections.abc import Callable
import socket
import os

@dataclass
class HyprEvent:
    kind: str
    content: str

HYPRLAND_EVENT_SOCKET_PATH = os.path.join(
    os.environ["XDG_RUNTIME_DIR"],
    "hypr",
    os.environ["HYPRLAND_INSTANCE_SIGNATURE"],
    ".socket2.sock",
)

HYPRLAND_COMMAND_SOCKET_PATH = os.path.join(
    os.environ["XDG_RUNTIME_DIR"],
    "hypr",
    os.environ["HYPRLAND_INSTANCE_SIGNATURE"],
    ".socket.sock",
)

def listen_hyprland_socket(handle: Callable[[HyprEvent], None]):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(HYPRLAND_EVENT_SOCKET_PATH)
    buffer = b""
    while True:
        buffer += sock.recv(4096)
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.decode("utf-8")
            kind, content = line.split(">>")
            ev = HyprEvent(kind, content)
            handle(ev)


