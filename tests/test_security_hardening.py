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

    def test_update_setting_sensitive_classes(self):
        """Ensure sensitive_classes can be customized via update_setting."""
        from hyprsmart.config import update_setting
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_cfg_file = Path(tmp_dir) / "config.yaml"
            with patch("hyprsmart.config.CONFIG_DIR", Path(tmp_dir)), patch("hyprsmart.config.CONFIG_FILE", tmp_cfg_file):
                ok, msg, cfg = update_setting("sensitive_classes", "keepassxc, my_secret_app, BitWarden")
                self.assertTrue(ok)
                self.assertIn("keepassxc", cfg.sensitive_classes)
                self.assertIn("my_secret_app", cfg.sensitive_classes)
                self.assertIn("bitwarden", cfg.sensitive_classes)

                # Reset to empty
                ok, msg, cfg = update_setting("sensitive_classes", "empty")
                self.assertTrue(ok)
                self.assertEqual(cfg.sensitive_classes, [])

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

    def test_blacklist_auto_create_readonly(self):
        """Ensure load_blacklist automatically initializes blacklist.yaml with 0444 read-only permissions."""
        from hyprsmart.config import get_blacklist_info, load_blacklist
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_bl = Path(tmp_dir) / "blacklist.yaml"
            with patch("hyprsmart.config.CONFIG_DIR", Path(tmp_dir)), patch("hyprsmart.config.BLACKLIST_FILE", tmp_bl):
                classes = load_blacklist()
                self.assertTrue(tmp_bl.exists())
                mode = tmp_bl.stat().st_mode & 0o777
                # Must be 0o444 (no write permissions)
                self.assertEqual(mode & 0o222, 0, f"Expected read-only 0444, got {oct(mode)}")
                self.assertIn("keepassxc", classes)
                self.assertIn("1password", classes)

                info = get_blacklist_info()
                self.assertTrue(info["exists"])
                self.assertTrue(info["is_readonly"])

    def test_blacklist_load_custom_and_fallback(self):
        """Ensure load_blacklist parses custom classes and normalizes, with fallback on error."""
        from hyprsmart.config import load_blacklist
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_bl = Path(tmp_dir) / "blacklist.yaml"
            tmp_bl.write_text("sensitive_classes:\n  - MySecretVault\n  - '  KeePassXC  '\n", encoding="utf-8")
            with patch("hyprsmart.config.CONFIG_DIR", Path(tmp_dir)), patch("hyprsmart.config.BLACKLIST_FILE", tmp_bl):
                classes = load_blacklist()
                self.assertEqual(classes, ["keepassxc", "mysecretvault"])

                # Corrupt file test
                tmp_bl.chmod(0o600)
                tmp_bl.write_text(":::invalid:yaml:content", encoding="utf-8")
                fallback_classes = load_blacklist()
                self.assertIn("keepassxc", fallback_classes)

    def test_blacklist_save_direct_readonly(self):
        """Ensure save_blacklist with force_direct writes file and enforces 0444 mode."""
        from hyprsmart.config import load_blacklist, save_blacklist
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_bl = Path(tmp_dir) / "blacklist.yaml"
            with patch("hyprsmart.config.CONFIG_DIR", Path(tmp_dir)), patch("hyprsmart.config.BLACKLIST_FILE", tmp_bl):
                ok, msg = save_blacklist(["custom_app", "another_app"], target_path=tmp_bl, force_direct=True)
                self.assertTrue(ok)
                mode = tmp_bl.stat().st_mode & 0o777
                self.assertEqual(mode & 0o222, 0, f"Expected read-only permissions, got {oct(mode)}")
                loaded = load_blacklist()
                self.assertEqual(loaded, ["another_app", "custom_app"])

    def test_blacklist_save_escalation_install_command(self):
        """Ensure save_blacklist invokes privilege escalation via install -m 0444 -D."""
        import subprocess
        from hyprsmart.config import save_blacklist
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_bl = Path(tmp_dir) / "blacklist.yaml"
            with patch("hyprsmart.config.CONFIG_DIR", Path(tmp_dir)), \
                 patch("hyprsmart.config.BLACKLIST_FILE", tmp_bl), \
                 patch("hyprsmart.config.find_escalation_tool", return_value="/usr/bin/pkexec"), \
                 patch("subprocess.run") as mock_run:
                ok, msg = save_blacklist(["shielded_app"], target_path=tmp_bl, force_direct=False)
                self.assertTrue(ok)
                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                self.assertEqual(call_args[0], "/usr/bin/pkexec")
                self.assertEqual(call_args[1], "install")
                self.assertEqual(call_args[2], "-m")
                self.assertEqual(call_args[3], "0444")
                self.assertEqual(call_args[4], "-D")
                self.assertEqual(call_args[6], str(tmp_bl.resolve()))
                # Verify temp file was cleaned up
                tmp_src = Path(call_args[5])
                self.assertFalse(tmp_src.exists(), "Temporary file should be removed after install")

    def test_blacklist_save_escalation_fallback_to_sudo(self):
        """Ensure pkexec failure triggers fallback to sudo when available."""
        import subprocess
        from hyprsmart.config import save_blacklist
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_bl = Path(tmp_dir) / "blacklist.yaml"
            with patch("hyprsmart.config.CONFIG_DIR", Path(tmp_dir)), \
                 patch("hyprsmart.config.BLACKLIST_FILE", tmp_bl), \
                 patch("hyprsmart.config.find_escalation_tool", return_value="/usr/bin/pkexec"), \
                 patch("shutil.which", return_value="/usr/bin/sudo"):
                # First run (pkexec) raises CalledProcessError, second (sudo) succeeds
                mock_run = MagicMock(side_effect=[
                    subprocess.CalledProcessError(126, ["pkexec", "install"]),
                    MagicMock(returncode=0),
                ])
                with patch("subprocess.run", mock_run):
                    ok, msg = save_blacklist(["shielded_app"], target_path=tmp_bl, force_direct=False)
                    self.assertTrue(ok)
                    self.assertEqual(mock_run.call_count, 2)
                    self.assertEqual(mock_run.call_args_list[1][0][0][0], "/usr/bin/sudo")

    def test_blacklist_save_escalation_failure_handled(self):
        """Ensure escalation failure returns (False, error_msg) gracefully."""
        import subprocess
        from hyprsmart.config import save_blacklist
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_bl = Path(tmp_dir) / "blacklist.yaml"
            with patch("hyprsmart.config.CONFIG_DIR", Path(tmp_dir)), \
                 patch("hyprsmart.config.BLACKLIST_FILE", tmp_bl), \
                 patch("hyprsmart.config.find_escalation_tool", return_value="/usr/bin/pkexec"), \
                 patch("shutil.which", return_value=None), \
                 patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["pkexec"])):
                ok, msg = save_blacklist(["shielded_app"], target_path=tmp_bl, force_direct=False)
                self.assertFalse(ok)
                self.assertIn("failed", msg.lower())

    def test_blacklist_mtime_triggers_config_reload(self):
        """Ensure get_current_config reloads when blacklist.yaml mtime changes."""
        from hyprsmart.config import get_current_config, load_config
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_cfg = Path(tmp_dir) / "config.yaml"
            tmp_bl = Path(tmp_dir) / "blacklist.yaml"
            tmp_bl.write_text("sensitive_classes:\n  - initial_app\n", encoding="utf-8")
            with patch("hyprsmart.config.CONFIG_DIR", Path(tmp_dir)), \
                 patch("hyprsmart.config.CONFIG_FILE", tmp_cfg), \
                 patch("hyprsmart.config.BLACKLIST_FILE", tmp_bl):
                cfg1 = load_config()
                self.assertEqual(cfg1.sensitive_classes, ["initial_app"])

                # Update blacklist file and mtime
                new_mtime = tmp_bl.stat().st_mtime + 2.0
                tmp_bl.write_text("sensitive_classes:\n  - initial_app\n  - updated_app\n", encoding="utf-8")
                os.utime(tmp_bl, (new_mtime, new_mtime))

                cfg2 = get_current_config()
                self.assertIn("updated_app", cfg2.sensitive_classes)

    def test_config_yaml_does_not_contain_sensitive_classes(self):
        """Ensure save_config writes config.yaml without sensitive_classes."""
        import yaml
        from hyprsmart.config import HyprsmartConfig, save_config
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_cfg = Path(tmp_dir) / "config.yaml"
            with patch("hyprsmart.config.CONFIG_DIR", Path(tmp_dir)), patch("hyprsmart.config.CONFIG_FILE", tmp_cfg):
                cfg = HyprsmartConfig(target_contrast=7.5, sensitive_classes=["keepassxc", "vault"])
                save_config(cfg)

                raw_data = yaml.safe_load(tmp_cfg.read_text(encoding="utf-8"))
                self.assertNotIn("sensitive_classes", raw_data, "config.yaml must not store sensitive_classes")
                self.assertEqual(raw_data["target_contrast"], 7.5)

    def test_cli_cmd_blacklist_actions(self):
        """Ensure CLI cmd_blacklist correctly handles list, add, remove, and lock."""
        import argparse
        from hyprsmart.cli import cmd_blacklist
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_bl = Path(tmp_dir) / "blacklist.yaml"
            tmp_bl.write_text("sensitive_classes:\n  - keepassxc\n  - bitwarden\n", encoding="utf-8")
            with patch("hyprsmart.config.CONFIG_DIR", Path(tmp_dir)), \
                 patch("hyprsmart.config.BLACKLIST_FILE", tmp_bl), \
                 patch("hyprsmart.cli.send_control_command", return_value={"status": "ok"}):

                # 1. List
                args_list = argparse.Namespace(blacklist_action="list")
                cmd_blacklist(args_list)

                # 2. Add invalid class name (should reject)
                args_add_invalid = argparse.Namespace(blacklist_action="add", classes=["invalid class!"])
                cmd_blacklist(args_add_invalid)
                self.assertNotIn("invalid class!", tmp_bl.read_text(encoding="utf-8"))

                # 3. Add valid class name
                with patch("hyprsmart.config.find_escalation_tool", return_value=None):
                    args_add = argparse.Namespace(blacklist_action="add", classes=["my_vault", "1password"])
                    cmd_blacklist(args_add)
                    content = tmp_bl.read_text(encoding="utf-8")
                    self.assertIn("my_vault", content)
                    self.assertIn("1password", content)

                    # 4. Remove class
                    args_remove = argparse.Namespace(blacklist_action="remove", classes=["bitwarden"])
                    cmd_blacklist(args_remove)
                    content_after = tmp_bl.read_text(encoding="utf-8")
                    self.assertNotIn("bitwarden", content_after)
                    self.assertIn("keepassxc", content_after)

                    # 5. Lock
                    args_lock = argparse.Namespace(blacklist_action="lock", system=False)
                    cmd_blacklist(args_lock)
                    mode = tmp_bl.stat().st_mode & 0o777
                    self.assertEqual(mode & 0o222, 0)


if __name__ == "__main__":
    unittest.main()
