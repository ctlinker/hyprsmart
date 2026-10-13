import unittest
import numpy as np

from hyprsmart.config import HyprsmartConfig
from hyprsmart.opacity.backdrop import Backdrop, backdrop_behind, get_cached_wallpaper_luminance
from hyprsmart.opacity.compute import decide_opacity
from hyprsmart.primitive.window import Window


class TestHyprsmartCore(unittest.TestCase):
    def test_backdrop_behind_slicing(self):
        # lum matrix of height=100, width=200
        lum = np.ones((100, 200), dtype=np.float32) * 0.2
        # Place a bright region at y in [10, 20), x in [10, 20)
        lum[10:20, 10:20] = 0.8

        # Window at x=40, y=40, width=40, height=40 (DOWN=4 => x in [10, 20), y in [10, 20))
        win = Window(
            title="Test Window",
            address="0x123",
            x=40.0,
            y=40.0,
            width=40.0,
            height=40.0,
        )

        b = backdrop_behind(lum, win, monitor_x=0, monitor_y=0)
        self.assertAlmostEqual(b.p5, 0.8, places=2)
        self.assertAlmostEqual(b.p95, 0.8, places=2)

    def test_backdrop_behind_out_of_bounds(self):
        lum = np.full((100, 200), 0.5, dtype=np.float32)
        win = Window(
            title="Offscreen",
            address="0x456",
            x=2000.0,
            y=2000.0,
            width=100.0,
            height=100.0,
        )
        b = backdrop_behind(lum, win, monitor_x=0, monitor_y=0)
        self.assertIsInstance(b, Backdrop)
        self.assertEqual(b.p5, 0.5)

    def test_decide_opacity(self):
        b_dark = Backdrop(p5=0.1, p95=0.2, std=0.05)
        # White text (0.95), dark window background (0.05) on dark wallpaper
        alpha = decide_opacity(text_l=0.95, bg_l=0.05, b=b_dark, target=4.5, floor=0.5)
        self.assertTrue(0.5 <= alpha <= 1.0)

    def test_config_resolution(self):
        cfg = HyprsmartConfig(
            monitors={"0": "/path/to/wall0.png", "HDMI-A-1": "/path/to/wall1.png"},
            default_wallpaper="/path/to/default.png",
        )
        self.assertEqual(cfg.get_wallpaper("eDP-1", 0), "/path/to/wall0.png")
        self.assertEqual(cfg.get_wallpaper("HDMI-A-1", 1), "/path/to/wall1.png")
        self.assertEqual(cfg.get_wallpaper("DP-1", 2), "/path/to/default.png")

    def test_cached_wallpaper_fallback(self):
        lum = get_cached_wallpaper_luminance("/non/existent/wallpaper.png", 1920, 1080)
        self.assertEqual(lum.shape, (1080 // 4, 1920 // 4))

    def test_window_parsing_safety(self):
        from hyprsmart.primitive.window import window_from_hyprctl_json_dict
        self.assertIsNone(window_from_hyprctl_json_dict({}))
        self.assertIsNone(window_from_hyprctl_json_dict(None))
        self.assertIsNone(window_from_hyprctl_json_dict({"address": "0x123"}))


if __name__ == "__main__":
    unittest.main()
