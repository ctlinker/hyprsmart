import unittest
import numpy as np

from hyprsmart.config import HyprsmartConfig
from hyprsmart.opacity.backdrop import (
    Backdrop,
    backdrop_behind,
    compute_sobel_energy,
    get_cached_wallpaper_backdrop_data,
    get_cached_wallpaper_luminance,
)
from hyprsmart.opacity.compute import decide_opacity
from hyprsmart.opacity.win_col import WindowVisuals
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
        self.assertGreater(b.edge_energy, 0.0)

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

    def test_sobel_energy(self):
        # Flat image should have near zero gradient energy
        flat = np.full((50, 50), 0.4, dtype=np.float32)
        grad_flat = compute_sobel_energy(flat)
        self.assertAlmostEqual(float(np.mean(grad_flat)), 0.0, places=4)

        # High-frequency vertical stripes should have high gradient energy
        stripes = np.zeros((50, 50), dtype=np.float32)
        stripes[:, ::2] = 1.0
        grad_stripes = compute_sobel_energy(stripes)
        self.assertGreater(float(np.mean(grad_stripes)), 0.10)

    def test_decide_opacity_legacy_signature(self):
        b_dark = Backdrop(
            p5=0.1, p95=0.2, p15=0.12, p85=0.18, median=0.15, std=0.05, edge_energy=0.02
        )
        alpha = decide_opacity(text_l=0.95, bg_l=0.05, b=b_dark, target=4.5, floor=0.5)
        self.assertTrue(0.5 <= alpha <= 1.0)

    def test_decide_opacity_adaptive_terminal(self):
        # Dark terminal: black background (0.01), white text (0.95), high background ratio (0.85), sparse text (0.10)
        tty_vis = WindowVisuals(
            text_l=0.95,
            bg_l=0.01,
            text_density=0.10,
            bg_ratio=0.85,
        )

        # 1. On a calm wallpaper with low edge clutter:
        # Should allow deep transparency (~0.5 - 0.7) rather than staying locked at 1.0!
        b_calm = Backdrop(
            p5=0.05, p95=0.75, p15=0.10, p85=0.45, median=0.20, std=0.10, edge_energy=0.02
        )
        alpha_calm = decide_opacity(tty_vis, b_calm, target=4.5, floor=0.5)
        self.assertLessEqual(alpha_calm, 0.75)
        self.assertGreaterEqual(alpha_calm, 0.50)

        # 2. On a busy/high-contrast wallpaper with high edge energy:
        # Should preserve opacity (higher alpha to protect readability)
        b_busy = Backdrop(
            p5=0.05, p95=0.90, p15=0.10, p85=0.80, median=0.40, std=0.30, edge_energy=0.20
        )
        alpha_busy = decide_opacity(tty_vis, b_busy, target=4.5, floor=0.5)
        self.assertGreater(alpha_busy, alpha_calm)

    def test_window_visuals_unpacking(self):
        vis = WindowVisuals(text_l=0.9, bg_l=0.1, text_density=0.25, bg_ratio=0.75)
        t, bg = vis
        self.assertEqual(t, 0.9)
        self.assertEqual(bg, 0.1)

    def test_config_resolution(self):
        cfg = HyprsmartConfig(
            monitors={"0": "/path/to/wall0.png", "HDMI-A-1": "/path/to/wall1.png"},
            default_wallpaper="/path/to/default.png",
        )
        self.assertEqual(cfg.get_wallpaper("eDP-1", 0), "/path/to/wall0.png")
        self.assertEqual(cfg.get_wallpaper("HDMI-A-1", 1), "/path/to/wall1.png")
        self.assertEqual(cfg.get_wallpaper("DP-1", 2), "/path/to/default.png")

    def test_cached_wallpaper_fallback(self):
        lum, grad = get_cached_wallpaper_backdrop_data("/non/existent/wallpaper.png", 1920, 1080)
        self.assertEqual(lum.shape, (1080 // 4, 1920 // 4))
        self.assertEqual(grad.shape, (1080 // 4, 1920 // 4))

    def test_window_parsing_safety(self):
        from hyprsmart.primitive.window import window_from_hyprctl_json_dict
        self.assertIsNone(window_from_hyprctl_json_dict({}))
        self.assertIsNone(window_from_hyprctl_json_dict(None))
        self.assertIsNone(window_from_hyprctl_json_dict({"address": "0x123"}))


if __name__ == "__main__":
    unittest.main()
