import os
from pathlib import Path
from queue import Empty, Full, Queue
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from hyprsmart.config import (
    DEFAULT_SENSITIVE_CLASSES,
    HyprsmartConfig,
    is_sensitive_window,
    save_config,
)
from hyprsmart.daemon.control_server import (
    ControlServer,
    get_control_socket_path,
    get_runtime_dir,
    send_control_command,
)
from hyprsmart.daemon.handle import (
    _enqueue_capture,
    _enqueue_luminance,
    CAPTURE_QUEUE,
    LUMINANCE_QUEUE,
)
from hyprsmart.opacity.backdrop import get_cached_wallpaper_backdrop_data, load_wallpaper
from hyprsmart.primitive.window import Window, set_hyprland_win_opacity


class TestSecurityHardening(unittest.TestCase):
    def test_address_validation_rejects_unsafe_address(self):
        """Ensure window address is strictly validated as hexadecimal before dispatching."""
        # Unsafe addresses with command separators, quotes, spaces, or invalid syntax
        unsafe_addresses = [
            "0x1234; rm -rf /",
            '0x1234", prop = "evil',
            "0x1234\n0x5678",
            "not_an_address",
            "",
            "0xGHIJ",  # non-hex
            "0x" + "a" * 32,  # excessively long
        ]
        for addr in unsafe_addresses:
            with self.subTest(addr=addr):
                with self.assertRaises(ValueError):
                    set_hyprland_win_opacity(addr, 0.8, 0.8)

        # Valid hexadecimal address should pass validation (mocking subprocess.run to avoid actual hyprctl call)
        with patch("subprocess.run") as mock_run:
            set_hyprland_win_opacity("0x55d7b3a4e900", 0.75, 0.75)
            self.assertEqual(mock_run.call_count, 2)

    def test_sensitive_window_privacy_shield(self):
        """Ensure sensitive windows (password managers, auth prompts, incognito) are shielded."""
        cfg = HyprsmartConfig()

        # Sensitive windows by class
        for s_cls in DEFAULT_SENSITIVE_CLASSES:
            win = Window(title="Main Window", address="0x1111", x=0, y=0, width=800, height=600, window_class=s_cls)
            self.assertTrue(is_sensitive_window(win, cfg), f"Class {s_cls} should be marked sensitive")

        # Case-insensitive and prefix/suffix matching
        win_case = Window(title="Vault", address="0x2222", x=0, y=0, width=800, height=600, window_class="org.keepassxc.KeePassXC")
        self.assertTrue(is_sensitive_window(win_case, cfg))

        # Sensitive windows by title
        private_browser = Window(title="Mozilla Firefox (Private Browsing)", address="0x3333", x=0, y=0, width=800, height=600, window_class="firefox")
        self.assertTrue(is_sensitive_window(private_browser, cfg))

        incognito_chrome = Window(title="Google Chrome - Incognito", address="0x4444", x=0, y=0, width=800, height=600, window_class="google-chrome")
        self.assertTrue(is_sensitive_window(incognito_chrome, cfg))

        auth_prompt = Window(title="Authentication Required", address="0x5555", x=0, y=0, width=400, height=300, window_class="gcr-prompter")
        self.assertTrue(is_sensitive_window(auth_prompt, cfg))

        # Standard non-sensitive windows
        normal_win = Window(title="nvim handle.py", address="0x6666", x=0, y=0, width=800, height=600, window_class="kitty")
        self.assertFalse(is_sensitive_window(normal_win, cfg))

    def test_control_server_runtime_dir_and_permissions(self):
        """Ensure runtime dir and socket are restricted to user-only access (0700 / 0600)."""
        runtime_dir = get_runtime_dir()
        self.assertTrue(runtime_dir.exists())
        # Check permissions on runtime directory (must be 0700)
        stat_mode = oct(runtime_dir.stat().st_mode & 0o777)
        self.assertEqual(stat_mode, "0o700")

    def test_control_server_peer_cred_authorization(self):
        """Ensure peer authorization logic blocks unauthorized UIDs."""
        server = ControlServer(lambda req: {"status": "ok"})
        mock_sock = MagicMock()

        # Mock same UID: should be authorized
        with patch("hyprsmart.daemon.control_server.os.getuid", return_value=1000):
            with patch("hyprsmart.daemon.control_server.struct.unpack", return_value=(1234, 1000, 1000)):
                self.assertTrue(server._is_peer_authorized(mock_sock))

            # Mock different UID: must be rejected
            with patch("hyprsmart.daemon.control_server.struct.unpack", return_value=(5678, 1001, 1001)):
                self.assertFalse(server._is_peer_authorized(mock_sock))

    def test_atomic_config_save_permissions(self):
        """Ensure config is written atomically and with restricted permissions."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_cfg_file = Path(tmp_dir) / "config.yaml"
            with patch("hyprsmart.config.CONFIG_DIR", Path(tmp_dir)), patch("hyprsmart.config.CONFIG_FILE", tmp_cfg_file):
                cfg = HyprsmartConfig(target_contrast=7.0, floor_opacity=0.4)
                save_config(cfg)

                self.assertTrue(tmp_cfg_file.exists())
                # Permissions must be restricted (0o600 or 0o700 depending on umask, but no world access)
                mode = tmp_cfg_file.stat().st_mode & 0o777
                self.assertEqual(mode & 0o077, 0, "Config file should have no group/other permissions")

    def test_bounded_queues_drop_oldest(self):
        """Ensure bounded queues do not grow unbounded and drop oldest entries under pressure."""
        # Drain queues first
        while not CAPTURE_QUEUE.empty():
            try:
                CAPTURE_QUEUE.get_nowait()
                CAPTURE_QUEUE.task_done()
            except Empty:
                break

        # Squeezing items past maxsize (8)
        for i in range(15):
            _enqueue_capture((f"win_{i}", False))

        self.assertLessEqual(CAPTURE_QUEUE.qsize(), 8)
        # Drain and verify freshest items remain
        items = []
        while not CAPTURE_QUEUE.empty():
            items.append(CAPTURE_QUEUE.get_nowait()[0])
            CAPTURE_QUEUE.task_done()

        self.assertEqual(len(items), 8)
        # Oldest items (0-6) should have been dropped; latest items (7-14) preserved
        self.assertEqual(items[-1], "win_14")

    def test_wallpaper_file_validation(self):
        """Ensure load_wallpaper and get_cached_wallpaper_backdrop_data reject non-regular files."""
        # Non-existent file
        with self.assertRaises(FileNotFoundError):
            load_wallpaper("/non/existent/path/to/wall.png", 1920, 1080)

        # Directory instead of file
        with self.assertRaises(FileNotFoundError):
            load_wallpaper(tempfile.gettempdir(), 1920, 1080)

        # get_cached_wallpaper_backdrop_data safely returns fallback neutral background
        lum, grad = get_cached_wallpaper_backdrop_data(tempfile.gettempdir(), 1920, 1080)
        self.assertEqual(lum.shape[0] > 0, True)
        self.assertAlmostEqual(float(lum[0, 0]), 0.2, places=1)


if __name__ == "__main__":
    unittest.main()
