import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image

import hyprsmart.config
import hyprsmart.daemon.cache as cache
from hyprsmart.config import HyprsmartConfig, update_setting
from hyprsmart.daemon.cache import (
    cache_clear,
    get_adaptive_reeval_budget,
    get_class_profile,
    record_class_probing_session,
)
from hyprsmart.daemon.handle import (
    DebouncedScheduler,
    ProgressiveReevaluator,
    handle_event,
)
from hyprsmart.daemon.socket import HyprEvent
from hyprsmart.opacity.win_col import WindowVisuals, unblend_luminance, visual_delta
from hyprsmart.primitive.get_mon import Monitor
from hyprsmart.primitive.window import Window


def _make_png_bytes(rgb_tuple: tuple[int, int, int], text_rgb: tuple[int, int, int] = (240, 240, 240)) -> bytes:
    """Create a synthetic 128x128 PNG image with a solid background and some text-like stripes."""
    arr = np.full((128, 128, 3), rgb_tuple, dtype=np.uint8)
    # Draw crisp high-contrast horizontal bars to simulate text glyphs
    arr[20:24, 16:112] = text_rgb
    arr[36:40, 16:96] = text_rgb
    arr[52:56, 16:104] = text_rgb
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


class TestProgressiveReevaluation(unittest.TestCase):
    def setUp(self):
        hyprsmart.config._CURRENT_CONFIG = None
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.tmp_config_file = self.tmp_path / "config.yaml"
        self.tmp_profiles_file = self.tmp_path / "profiles.json"

        self.p1 = patch("hyprsmart.config.CONFIG_DIR", self.tmp_path)
        self.p2 = patch("hyprsmart.config.CONFIG_FILE", self.tmp_config_file)
        self.p3 = patch("hyprsmart.daemon.cache.CONFIG_DIR", self.tmp_path)
        self.p4 = patch("hyprsmart.daemon.cache.PROFILES_FILE", self.tmp_profiles_file)
        self.p1.start()
        self.p2.start()
        self.p3.start()
        self.p4.start()
        cache_clear()

    def tearDown(self):
        hyprsmart.config._CURRENT_CONFIG = None
        self.p4.stop()
        self.p3.stop()
        self.p2.stop()
        self.p1.stop()
        self.tmp_dir.cleanup()
        cache_clear()

    def test_reeval_settings_validation(self):
        ok, msg, cfg = update_setting("reeval_max_ticks", "11")
        self.assertTrue(ok)
        self.assertEqual(cfg.reeval_max_ticks, 11)

        ok, msg, cfg = update_setting("reeval_stable_ticks", "8")
        self.assertTrue(ok)
        self.assertEqual(cfg.reeval_stable_ticks, 8)

        ok, msg, cfg = update_setting("reeval_interval", "0.75")
        self.assertTrue(ok)
        self.assertAlmostEqual(cfg.reeval_interval, 0.75)

        ok, msg, _ = update_setting("reeval_max_ticks", "50")
        self.assertFalse(ok)
        self.assertIn("exceeds maximum", msg)

    def test_polarity_flip_bypasses_class_regularization(self):
        # Learned class profile is dark (bg_l = 0.05), but a white webpage (0.95) is loaded
        # while the window is at alpha = 0.60 over a dark wallpaper (0.05).
        composite_l = 0.60 * 0.95 + 0.40 * 0.05
        recovered = unblend_luminance(
            composite_l,
            alpha=0.60,
            backdrop_l=0.05,
            class_ref_l=0.05,
        )
        # Because |0.95 - 0.05| = 0.90 > 0.25, class_ref_l must NOT pull 0.95 down!
        self.assertAlmostEqual(recovered, 0.95, places=4)

    def test_emergent_class_profile_budget_scaling(self):
        # 1. Cold-start (< 5 samples): uses full configured budget (11, 8)
        max_t, stable_t = get_adaptive_reeval_budget("new-browser", max_ticks_cfg=11, stable_ticks_cfg=8)
        self.assertEqual((max_t, stable_t), (11, 8))

        # 2. Train a static terminal class over 5 sessions with near-zero volatility
        term_vis = WindowVisuals(text_l=0.88, bg_l=0.02, text_density=0.12, bg_ratio=0.85)
        for _ in range(5):
            record_class_probing_session("foot", term_vis, max_delta=0.005, settle_time_sec=0.0)

        prof_term = get_class_profile("foot")
        self.assertIsNotNone(prof_term)
        self.assertEqual(prof_term.sample_count, 5)
        self.assertLess(prof_term.volatility, 0.02)

        # Static class scales down its required ticks automatically
        max_term, stable_term = get_adaptive_reeval_budget("foot", max_ticks_cfg=11, stable_ticks_cfg=8)
        self.assertLess(max_term, 11)
        self.assertLess(stable_term, 8)

        # 3. Train a volatile browser class over 5 sessions that settles around 4s
        browser_vis = WindowVisuals(text_l=0.10, bg_l=0.92, text_density=0.18, bg_ratio=0.72)
        for _ in range(5):
            record_class_probing_session("firefox", browser_vis, max_delta=0.65, settle_time_sec=4.0)

        prof_browser = get_class_profile("firefox")
        self.assertIsNotNone(prof_browser)
        self.assertGreater(prof_browser.volatility, 0.20)
        self.assertGreater(prof_browser.settle_time, 2.5)

        max_br, stable_br = get_adaptive_reeval_budget("firefox", max_ticks_cfg=11, stable_ticks_cfg=8)
        self.assertEqual(max_br, 11)
        self.assertGreaterEqual(stable_br, 7)

    @patch("hyprsmart.daemon.handle.apply_window_decision")
    @patch("hyprsmart.daemon.handle.get_hyprland_monitors")
    @patch("hyprsmart.daemon.handle.get_hyprland_active_window")
    @patch("hyprsmart.daemon.handle.capture_window")
    def test_progressive_session_tracks_website_load_and_converges(
        self,
        mock_capture,
        mock_get_active_win,
        mock_get_monitors,
        mock_apply_decision,
    ):
        # Configure 11 max ticks, 8 stable ticks required
        update_setting("reeval_max_ticks", "11")
        update_setting("reeval_stable_ticks", "8")
        update_setting("reeval_interval", "1.0")

        mock_mon = Monitor(id=0, name="eDP-1", x=0, y=0, width=1920, height=1080, scale=1.0)
        mock_get_monitors.return_value = [mock_mon]

        win = Window(
            title="Loading... - Mozilla Firefox",
            address="0xbeef",
            x=0,
            y=0,
            width=1200,
            height=800,
            window_class="firefox",
            monitor_id=0,
        )
        mock_get_active_win.return_value = win

        dark_loading_png = _make_png_bytes((15, 15, 18), (180, 180, 180))
        bright_loaded_png = _make_png_bytes((245, 245, 248), (20, 20, 25))

        # Use a mock scheduler so we can step ticks deterministically without sleeping
        mock_scheduler = MagicMock(spec=DebouncedScheduler)
        reeval = ProgressiveReevaluator(mock_scheduler)

        init_vis = WindowVisuals(text_l=0.75, bg_l=0.01, text_density=0.05, bg_ratio=0.90)
        session = reeval.start_session(win, initial_visuals=init_vis, initial_alpha=0.70)
        self.assertIsNotNone(session)
        self.assertEqual(session.max_ticks, 11)
        self.assertEqual(session.stable_ticks_target, 8)

        # Simulate ticks 1 and 2: still showing dark loading screen
        mock_capture.return_value = dark_loading_png
        self.assertTrue(reeval.step_tick(session))  # tick 1
        self.assertTrue(reeval.step_tick(session))  # tick 2

        # Simulate tick 3: webpage finishes loading and paints bright white background!
        mock_capture.return_value = bright_loaded_png
        mock_apply_decision.reset_mock()
        self.assertTrue(reeval.step_tick(session))  # tick 3 -> huge visual jump!
        self.assertEqual(session.stable_ticks, 0)
        self.assertEqual(session.last_change_tick, 3)
        self.assertGreater(session.max_delta, 0.50)
        # Opacity decision was re-evaluated on tick 3
        self.assertEqual(mock_apply_decision.call_count, 1)

        # Simulate ticks 4..10: page stays static on bright_loaded_png (pixel-identical short-circuit!)
        mock_apply_decision.reset_mock()
        for expected_tick in range(4, 11):
            cont = reeval.step_tick(session)
            self.assertEqual(session.current_tick, expected_tick)
            self.assertTrue(cont)

        # On tick 11 (8th consecutive stable tick after tick 3: ticks 4,5,6,7,8,9,10,11 -> 8 stable ticks),
        # session converges and finalizes!
        cont = reeval.step_tick(session)
        self.assertFalse(cont)
        self.assertIsNone(reeval.active_session)
        # Pixel short-circuit skipped redundant apply_window_decision calls during stable ticks
        self.assertEqual(mock_apply_decision.call_count, 0)

        # Verify emergent profile was saved to CLASS_PROFILES and profiles.json
        prof = get_class_profile("firefox")
        self.assertIsNotNone(prof)
        self.assertEqual(prof.sample_count, 1)
        self.assertGreater(prof.volatility, 0.50)
        self.assertAlmostEqual(prof.settle_time, 3.0, places=2)

    def test_progressive_session_canceled_on_focus_switch_or_close(self):
        mock_scheduler = MagicMock(spec=DebouncedScheduler)
        reeval = ProgressiveReevaluator(mock_scheduler)

        win1 = Window(
            title="Tab 1", address="0x1111", x=0, y=0, width=800, height=600, window_class="firefox"
        )
        vis1 = WindowVisuals(text_l=0.8, bg_l=0.05, text_density=0.1, bg_ratio=0.8)
        session = reeval.start_session(win1, initial_visuals=vis1)
        self.assertIsNotNone(reeval.active_session)

        # Canceling with a different window address leaves session intact
        reeval.cancel("0x2222")
        self.assertIsNotNone(reeval.active_session)

        # Canceling with matching window address cancels immediately
        reeval.cancel("0x1111")
        self.assertIsNone(reeval.active_session)
        self.assertTrue(session.cancelled)

    def test_visual_delta_scales_texture_noise(self):
        v1 = WindowVisuals(text_l=0.80, bg_l=0.05, text_density=0.10, bg_ratio=0.80)
        # Blinking cursor or small widget alters text_density and bg_ratio by 0.04
        v2 = WindowVisuals(text_l=0.80, bg_l=0.05, text_density=0.14, bg_ratio=0.84)
        delta = visual_delta(v1, v2)
        # Scaled by 0.50 -> 0.04 * 0.50 = 0.02, which is below the 0.03 threshold
        self.assertAlmostEqual(delta, 0.02, places=4)
        self.assertLess(delta, 0.03)

    @patch("hyprsmart.daemon.handle.apply_window_decision")
    @patch("hyprsmart.daemon.handle.get_hyprland_monitors")
    @patch("hyprsmart.daemon.handle.get_hyprland_active_window")
    @patch("hyprsmart.daemon.handle.capture_window")
    def test_anti_hunting_dampens_micro_fluctuations(
        self,
        mock_capture,
        mock_get_active_win,
        mock_get_monitors,
        mock_apply_decision,
    ):
        mock_mon = Monitor(id=0, name="eDP-1", x=0, y=0, width=1920, height=1080, scale=1.0)
        mock_get_monitors.return_value = [mock_mon]

        win = Window(
            title="Dynamic Page",
            address="0xcafe",
            x=0,
            y=0,
            width=1000,
            height=700,
            window_class="browser",
        )
        mock_get_active_win.return_value = win

        # Synthetic image that produces a minor visual fluctuation
        png1 = _make_png_bytes((20, 20, 20), (220, 220, 220))
        # Slightly altered image (small texture variation)
        png2 = _make_png_bytes((20, 20, 20), (230, 230, 230))

        mock_scheduler = MagicMock(spec=DebouncedScheduler)
        reeval = ProgressiveReevaluator(mock_scheduler)

        init_vis = WindowVisuals(text_l=0.70, bg_l=0.02, text_density=0.10, bg_ratio=0.80)
        session = reeval.start_session(win, initial_visuals=init_vis, initial_alpha=0.65)
        self.assertEqual(session.smoothed_alpha, 0.65)

        # Step tick 1 with png2
        mock_capture.return_value = png2
        reeval.step_tick(session)
        # If solver wanted 0.70 (a 0.05 step jump), smoothed_alpha should be damped (e.g. 0.67)
        # rather than wildly jumping by a full 0.05 step
        self.assertLessEqual(session.smoothed_alpha, 0.70)
        self.assertGreaterEqual(session.smoothed_alpha, 0.65)


if __name__ == "__main__":
    unittest.main()
