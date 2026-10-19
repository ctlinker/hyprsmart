import subprocess
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from hyprsmart.daemon.handle import (
    CURRENT_ACTIVE_ADDRESS,
    handle_event,
    SCHEDULER,
)
from hyprsmart.daemon.socket import HyprEvent
from hyprsmart.daemon.cache import (
    CLASS_PROFILES,
    get_adaptive_reeval_budget,
    record_class_probing_session,
)
from hyprsmart.opacity.backdrop import _luminance
from hyprsmart.opacity.video_detect import get_active_audio_pids, is_pid_emitting_audio
from hyprsmart.opacity.win_col import WindowVisuals, window_colors
from hyprsmart.primitive.window import Window, capture_window


class TestPerformanceOptimizations(unittest.TestCase):
    def test_capture_window_uses_low_overhead_flags(self):
        """Ensure capture_window calls grim with -l 0 (no zlib compression) and -s 1 (logical 1x scale)."""
        win = Window(title="Editor", address="0x1111", x=100, y=200, width=800, height=600)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"\x89PNG\r\n\x1a\n...")
            capture_window(win)
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            self.assertEqual(cmd[0], "grim")
            self.assertEqual(cmd[1:5], ["-l", "0", "-s", "1"])
            self.assertEqual(cmd[5], "-g")
            self.assertEqual(cmd[6], "100,200 800x600")

    def test_luminance_lut_matches_linear_formula(self):
        """Ensure fast LUT luminance matches nonlinear sRGB formula within float precision."""
        # Test all 256 pure grey levels
        grey_levels = np.array([[[i, i, i]] for i in range(256)], dtype=np.uint8)
        fast_lum = _luminance(grey_levels).ravel()

        # Compute pure analytical WCAG linear values
        c = np.arange(256, dtype=np.float32) / 255.0
        exact_linear = np.where(
            c <= 0.04045,
            c / 12.92,
            ((c + 0.055) / 1.055) ** 2.4,
        )
        # WCAG sum of weights is 0.2126 + 0.7152 + 0.0722 = 1.0
        max_diff = float(np.max(np.abs(fast_lum - exact_linear)))
        self.assertLess(max_diff, 1e-6, "LUT luminance should be bit-exact with analytical formula")

    def test_adaptive_reeval_budget_static_zero(self):
        """Ensure proven static window classes receive 0 ticks to avoid background capture loops."""
        # Train static terminal
        vis = WindowVisuals(text_l=0.90, bg_l=0.05, text_density=0.10, bg_ratio=0.88)
        for _ in range(5):
            record_class_probing_session("static-terminal", vis, max_delta=0.005, settle_time_sec=0.2)

        max_ticks, stable_ticks = get_adaptive_reeval_budget("static-terminal", max_ticks_cfg=11, stable_ticks_cfg=8)
        self.assertEqual(max_ticks, 0, "Static windows must have max_ticks=0 to bypass polling loops")
        self.assertEqual(stable_ticks, 1)

    def test_handle_event_drops_unfocused_window_title_updates(self):
        """Ensure windowtitlev2 events for unfocused background windows are dropped without scheduling."""
        import hyprsmart.daemon.handle as h

        # Set focused window address
        h.CURRENT_ACTIVE_ADDRESS = "0x1234"
        with patch.object(h.SCHEDULER, "schedule") as mock_schedule:
            # Title update for a different background window (0x9999)
            ev_bg = HyprEvent(kind="windowtitlev2", content="0x9999,Spotify Free")
            handle_event(ev_bg)
            mock_schedule.assert_not_called()

            # Title update for the active window (0x1234)
            ev_fg = HyprEvent(kind="windowtitlev2", content="0x1234,active - terminal")
            handle_event(ev_fg)
            mock_schedule.assert_called_once()
            self.assertEqual(mock_schedule.call_args[0][0], "active_window")

    def test_audio_cache_ttl(self):
        """Ensure active audio pids are cached and do not spawn pactl on every sub-second call."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='[{"properties": {"application.process.id": "42"}}]')
            pids1 = get_active_audio_pids(force_refresh=True)
            self.assertIn(42, pids1)
            self.assertEqual(mock_run.call_count, 1)

            # Subsequent call within TTL (2.0s) should use cache
            pids2 = get_active_audio_pids(force_refresh=False)
            self.assertEqual(pids1, pids2)
            self.assertEqual(mock_run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
