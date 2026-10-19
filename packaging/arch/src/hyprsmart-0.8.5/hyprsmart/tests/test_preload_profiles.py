import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from hyprsmart.primitive.window import Window
from hyprsmart.primitive.get_mon import Monitor
from hyprsmart.opacity.win_col import WindowVisuals
import hyprsmart.daemon.cache as cache
from hyprsmart.daemon.handle import preload_all_windows


class TestPreloadProfiles(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_config_dir = Path(self.tmp_dir.name)
        self.tmp_profiles_file = self.tmp_config_dir / "profiles.json"
        self.patcher1 = patch("hyprsmart.daemon.cache.CONFIG_DIR", self.tmp_config_dir)
        self.patcher2 = patch("hyprsmart.daemon.cache.PROFILES_FILE", self.tmp_profiles_file)
        self.patcher1.start()
        self.patcher2.start()
        cache.cache_clear()

    def tearDown(self):
        self.patcher2.stop()
        self.patcher1.stop()
        self.tmp_dir.cleanup()
        cache.cache_clear()

    def test_save_and_load_profiles_json(self):
        vis = WindowVisuals(text_l=0.75, bg_l=0.02, text_density=0.15, bg_ratio=0.82)
        cache.update_class_profile("test-term", vis)

        # Ensure file was written to disk
        self.assertTrue(self.tmp_profiles_file.exists())
        data = json.loads(self.tmp_profiles_file.read_text(encoding="utf-8"))
        self.assertIn("test-term", data)
        self.assertEqual(data["test-term"]["text_l"], 0.75)

        # Clear in-memory and reload from disk
        cache.CLASS_PROFILES.clear()
        self.assertIsNone(cache.get_class_profile("test-term"))
        loaded = cache.load_class_profiles()
        self.assertIn("test-term", loaded)
        self.assertEqual(loaded["test-term"].text_l, 0.75)

    @patch("hyprsmart.daemon.handle.apply_window_decision")
    @patch("hyprsmart.daemon.handle.get_hyprland_monitors")
    @patch("hyprsmart.daemon.handle.get_hyprland_windows")
    def test_preload_all_windows_applies_profiles(
        self, mock_get_windows, mock_get_monitors, mock_apply_decision
    ):
        mock_mon = Monitor(id=0, name="eDP-1", x=0, y=0, width=1920, height=1080, scale=1.0)
        mock_get_monitors.return_value = [mock_mon]

        win1 = Window(
            title="bash", address="0x1111", x=0, y=0, width=800, height=600, window_class="ghostty", monitor_id=0
        )
        win2 = Window(
            title="code", address="0x2222", x=800, y=0, width=800, height=600, window_class="unknown_app", monitor_id=0
        )
        mock_get_windows.return_value = [win1, win2]

        vis = WindowVisuals(text_l=0.8, bg_l=0.01, text_density=0.1, bg_ratio=0.85)
        cache.CLASS_PROFILES["ghostty"] = vis

        preload_all_windows()

        # Only win1 (ghostty) should have been preloaded because unknown_app has no profile
        self.assertEqual(mock_apply_decision.call_count, 1)
        called_win = mock_apply_decision.call_args[0][0]
        called_vis = mock_apply_decision.call_args[0][1]
        self.assertEqual(called_win.address, "0x1111")
        self.assertEqual(called_vis.text_l, 0.8)


if __name__ == "__main__":
    unittest.main()
