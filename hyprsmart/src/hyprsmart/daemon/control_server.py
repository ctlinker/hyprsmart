from collections.abc import Callable
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time

def get_runtime_dir() -> Path:
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        base = Path(xdg_runtime) / "hyprsmart"
    else:
        # Secure user-isolated fallback when XDG_RUNTIME_DIR is absent
        uid = os.geteuid() if hasattr(os, "geteuid") else (os.getuid() if hasattr(os, "getuid") else 1000)
        base = Path(tempfile.gettempdir()) / f"hyprsmart-{uid}"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(str(base), 0o700)
    except OSError:
        pass
    st = base.stat()
    expected_uid = os.geteuid() if hasattr(os, "geteuid") else (os.getuid() if hasattr(os, "getuid") else None)
    if expected_uid is not None and st.st_uid != expected_uid:
        raise PermissionError(f"Runtime directory {base} is not owned by current user (owner UID {st.st_uid} != current UID {expected_uid}).")
    return base

def get_control_socket_path() -> Path:
    return get_runtime_dir() / "control.sock"

def get_pid_file_path() -> Path:
    return get_runtime_dir() / "hyprsmart.pid"


class ControlServer:
    def __init__(self, command_handler: Callable[[dict], dict]):
        self.socket_path = get_control_socket_path()
        self.command_handler = command_handler
        self.stop_event = threading.Event()
        self.server_thread: threading.Thread | None = None

    def start(self) -> None:
        if self.socket_path.exists():
            try:
                st = self.socket_path.stat()
                expected_uid = os.geteuid() if hasattr(os, "geteuid") else (os.getuid() if hasattr(os, "getuid") else None)
                if expected_uid is not None and st.st_uid != expected_uid:
                    raise PermissionError(f"Socket {self.socket_path} exists and is not owned by current user.")
                self.socket_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                if isinstance(e, PermissionError):
                    raise

        self.server_thread = threading.Thread(target=self._run, daemon=True)
        self.server_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.socket_path.exists():
            try:
                st = self.socket_path.stat()
                expected_uid = os.geteuid() if hasattr(os, "geteuid") else (os.getuid() if hasattr(os, "getuid") else None)
                if expected_uid is None or st.st_uid == expected_uid:
                    self.socket_path.unlink()
            except OSError:
                pass

    def _is_peer_authorized(self, conn: socket.socket) -> bool:
        """Verify connecting peer UID matches daemon owner UID via SO_PEERCRED (fail-closed)."""
        try:
            SO_PEERCRED = getattr(socket, "SO_PEERCRED", 17)
            cred = conn.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize("3i"))
            _, peer_uid, _ = struct.unpack("3i", cred)
            expected_uid = os.geteuid() if hasattr(os, "geteuid") else (os.getuid() if hasattr(os, "getuid") else -1)
            return peer_uid == expected_uid
        except (OSError, struct.error, AttributeError):
            # Fail-closed: reject connection if credentials cannot be verified
            return False

    def _run(self) -> None:
        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(str(self.socket_path))
        try:
            os.chmod(str(self.socket_path), 0o600)
        except OSError:
            pass
        server_sock.listen(5)
        server_sock.settimeout(1.0)

        while not self.stop_event.is_set():
            try:
                conn, _ = server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

        server_sock.close()
        if self.socket_path.exists():
            try:
                st = self.socket_path.stat()
                expected_uid = os.geteuid() if hasattr(os, "geteuid") else (os.getuid() if hasattr(os, "getuid") else None)
                if expected_uid is None or st.st_uid == expected_uid:
                    self.socket_path.unlink()
            except OSError:
                pass

    def _handle_client(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(2.0)
            if not self._is_peer_authorized(conn):
                try:
                    payload = json.dumps({"status": "error", "error": "Unauthorized peer UID"}).encode("utf-8") + b"\n"
                    conn.sendall(payload)
                except Exception:
                    pass
                return

            data = b""
            while not self.stop_event.is_set():
                try:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    if b"\n" in data:
                        break
                except socket.timeout:
                    break

            if not data:
                return

            try:
                req = json.loads(data.decode("utf-8").strip())
                res = self.command_handler(req)
            except Exception as e:
                res = {"status": "error", "error": str(e)}

            try:
                payload = json.dumps(res).encode("utf-8") + b"\n"
                conn.sendall(payload)
            except Exception:
                pass


def send_control_command(cmd: dict, timeout: float = 3.0) -> dict:
    """Send a command to the running daemon via UNIX domain socket."""
    socket_path = get_control_socket_path()
    if not socket_path.exists():
        raise ConnectionRefusedError(f"HyprSmart daemon is not running (no socket at {socket_path})")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(socket_path))
        sock.sendall(json.dumps(cmd).encode("utf-8") + b"\n")

        buffer = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
            if b"\n" in buffer:
                break

        if not buffer:
            raise ConnectionError("Empty response from daemon")

        return json.loads(buffer.decode("utf-8").strip())
    finally:
        sock.close()
