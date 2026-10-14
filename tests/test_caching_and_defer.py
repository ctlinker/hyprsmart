import time
import unittest
from unittest.mock import MagicMock, patch

from hyprsmart.primitive.window import Window
from hyprsmart.opacity.win_col import WindowVisuals
from hyprsmart.daemon.cache import (
    WIN_CACHE,
    CLASS_CACHE,
    cache_clear,
    cache_drop,
    cache_get,
    cache_put,
    get_applied_alpha,
    record_applied_state,
)
from hyprsmart.daemon.handle import (
    DebouncedScheduler,
    DIFF_OPACITY_THRESHOLD,
    apply_window_decision,
)


class TestCachingAndDeferred(unittest.TestCase):
    def setUp(self):
        cache_clear()

    def test_class_cache_fallback(self):
        # Initial capture of a terminal
        win1 = Window(
            title="bash ~/Projects",
            address="0x1111",
            x=0,
            y=0,
            width=800,
            height=600,
            window_class="foot",
        )
        vis1 = WindowVisuals(
            text_l=0.92,
            bg_l=0.03,
            text_density=0.18,
            bg_ratio=0.82,
        )
        cache_put(win1, vis1)

        # 1. Exact match
        entry = cache_get(win1)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.visuals.text_l, 0.92)

        # 2. Same window, title changed (e.g. user ran nvim)
        win1_renamed = Window(
            title="nvim config.py",
            address="0x1111",
            x=0,
            y=0,
            width=800,
            height=600,
            window_class="foot",
        )
        entry2 = cache_get(win1_renamed)
        self.assertIsNotNone(entry2)
        # Should have fallen back to learned class visuals without recapturing
        self.assertEqual(entry2.visuals.text_l, 0.92)
        self.assertEqual(entry2.title, "nvim config.py")

        # 3. New second window of the same class (foot)
        win2 = Window(
            title="htop",
            address="0x2222",
            x=100,
            y=100,
            width=800,
            height=600,
            window_class="foot",
        )
        entry3 = cache_get(win2)
        self.assertIsNotNone(entry3)
        self.assertEqual(entry3.visuals.text_l, 0.92)

    def test_applied_alpha_tracking(self):
        win = Window(
            title="Editor",
            address="0x3333",
            x=0,
            y=0,
            width=1000,
            height=700,
            window_class="code",
        )
        vis = WindowVisuals(text_l=0.8, bg_l=0.1, text_density=0.2, bg_ratio=0.8)
        cache_put(win, vis)

        self.assertEqual(get_applied_alpha(win.address), 1.0)

        record_applied_state(win.address, 0.85, (0.1, 0.9, 0.02), (0, 0, 1000, 700))
        self.assertEqual(get_applied_alpha(win.address), 0.85)

    def test_debounced_scheduler_trailing_execution(self):
        scheduler = DebouncedScheduler()
        results = []

        def worker(val):
            results.append(val)

        # Rapidly schedule 3 calls for the same key within 10ms
        scheduler.schedule("test_key", 0.05, worker, "first")
        time.sleep(0.01)
        scheduler.schedule("test_key", 0.05, worker, "second")
        time.sleep(0.01)
        scheduler.schedule("test_key", 0.05, worker, "third")

        # Wait for the last timer to fire
        time.sleep(0.1)

        # Only the third call should have executed!
        self.assertEqual(results, ["third"])

    def test_debounced_scheduler_cancel(self):
        scheduler = DebouncedScheduler()
        results = []

        scheduler.schedule("cancel_key", 0.05, lambda: results.append("fired"))
        scheduler.cancel("cancel_key")
        time.sleep(0.08)

        self.assertEqual(results, [])

    @patch("hyprsmart.daemon.handle.set_hyprland_win_opacity")
    @patch("hyprsmart.daemon.handle.get_hyprland_active_monitor")
    @patch("hyprsmart.daemon.handle.get_cached_wallpaper_backdrop_data")
    @patch("hyprsmart.daemon.handle.decide_opacity")
    def test_opacity_diffing_skips_small_changes(
        self,
        mock_decide_opacity,
        mock_get_cached_wall,
        mock_get_mon,
        mock_set_opacity,
    ):
        # Setup monitor and mock returns
        mock_mon = MagicMock()
        mock_mon.name = "eDP-1"
        mock_mon.id = 0
        mock_mon.width = 1920
        mock_mon.height = 1080
        mock_mon.x = 0
        mock_mon.y = 0
        mock_get_mon.return_value = mock_mon

        import numpy as np
        wall_lum = np.zeros((1080, 1920), dtype=np.float32)
        wall_grad = np.zeros((1080, 1920), dtype=np.float32)
        mock_get_cached_wall.return_value = (wall_lum, wall_grad)

        win = Window(
            title="Terminal",
            address="0x4444",
            x=0,
            y=0,
            width=800,
            height=600,
            window_class="alacritty",
        )
        vis = WindowVisuals(text_l=0.9, bg_l=0.05, text_density=0.15, bg_ratio=0.85)
        cache_put(win, vis)

        # 1. First run: current is 1.0, ideal is 0.85 -> diff is 0.15 >= 0.03 -> DISPATCH
        mock_decide_opacity.return_value = 0.85
        apply_window_decision(win, vis, from_cache=False)
        mock_set_opacity.assert_called_once_with(win.address, 0.85, 0.85)
        self.assertEqual(get_applied_alpha(win.address), 0.85)

        mock_set_opacity.reset_mock()

        # 2. Second run: current is 0.85, ideal is 0.86 -> diff is 0.01 < 0.03 -> SKIP DISPATCH
        mock_decide_opacity.return_value = 0.86
        apply_window_decision(win, vis, from_cache=True)
        mock_set_opacity.assert_not_called()
        # Stored alpha remains 0.85
        self.assertEqual(get_applied_alpha(win.address), 0.85)

        # 3. Third run: ideal moves to 0.92 -> diff is 0.07 >= 0.03 -> DISPATCH
        mock_decide_opacity.return_value = 0.92
        apply_window_decision(win, vis, from_cache=True)
        mock_set_opacity.assert_called_once_with(win.address, 0.92, 0.92)
        self.assertEqual(get_applied_alpha(win.address), 0.92)


if __name__ == "__main__":
    unittest.main()
