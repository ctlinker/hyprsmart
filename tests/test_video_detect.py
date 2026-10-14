import unittest
from unittest.mock import patch, MagicMock

from hyprsmart.primitive.window import Window
from hyprsmart.opacity.win_col import WindowVisuals
from hyprsmart.opacity.video_detect import (
    evaluate_video_score,
    is_pid_emitting_audio,
)
from hyprsmart.config import (
    HyprsmartConfig,
    update_setting,
    get_current_config,
    save_config,
)


class TestVideoDetection(unittest.TestCase):
    def test_video_with_audio_and_idle_inhibit(self):
        win = Window(
            title="YouTube - Mozilla Firefox",
            address="0x1234",
            x=0,
            y=0,
            width=1920,
            height=1080,
            pid=4242,
            inhibiting_idle=True,
            fullscreen=False,
        )
        visuals = WindowVisuals(
            text_l=0.9,
            bg_l=0.1,
            text_density=0.08,
            bg_ratio=0.25,
        )
        # Mock active audio PID matching win.pid
        active_audio_pids = {4242}
        is_video, score, details = evaluate_video_score(
            win, visuals, active_audio_pids=active_audio_pids
        )
        self.assertTrue(is_video)
        self.assertGreaterEqual(score, 0.55)
        self.assertTrue(details["idle_inhibit"])
        self.assertTrue(details["audio_active"])
        self.assertTrue(details["visual_video"])

    def test_muted_video_with_idle_inhibit(self):
        win = Window(
            title="Video Lecture - MPV",
            address="0x5678",
            x=0,
            y=0,
            width=1280,
            height=720,
            pid=5555,
            inhibiting_idle=True,
            fullscreen=False,
        )
        visuals = WindowVisuals(
            text_l=0.8,
            bg_l=0.2,
            text_density=0.05,
            bg_ratio=0.15,
        )
        # No audio emitting
        active_audio_pids = set()
        is_video, score, details = evaluate_video_score(
            win, visuals, active_audio_pids=active_audio_pids
        )
        self.assertTrue(is_video)
        # 0.35 (idle) + 0.25 (visual) = 0.60 >= 0.55
        self.assertAlmostEqual(score, 0.60, places=2)
        self.assertTrue(details["idle_inhibit"])
        self.assertFalse(details["audio_active"])
        self.assertTrue(details["visual_video"])

    def test_music_player_audio_only(self):
        win = Window(
            title="Spotify",
            address="0x9999",
            x=0,
            y=0,
            width=1000,
            height=800,
            pid=7777,
            inhibiting_idle=False,
            fullscreen=False,
        )
        # Music player GUI with high solid background and UI text
        visuals = WindowVisuals(
            text_l=0.9,
            bg_l=0.05,
            text_density=0.35,
            bg_ratio=0.75,
        )
        active_audio_pids = {7777}
        is_video, score, details = evaluate_video_score(
            win, visuals, active_audio_pids=active_audio_pids
        )
        self.assertFalse(is_video)
        # Only audio (0.35) < 0.55
        self.assertAlmostEqual(score, 0.35, places=2)
        self.assertFalse(details["idle_inhibit"])
        self.assertTrue(details["audio_active"])
        self.assertFalse(details["visual_video"])

    def test_text_editor_or_terminal(self):
        win = Window(
            title="nvim: video_detect.py",
            address="0xaaaa",
            x=0,
            y=0,
            width=800,
            height=600,
            pid=1234,
            inhibiting_idle=False,
            fullscreen=False,
        )
        visuals = WindowVisuals(
            text_l=0.85,
            bg_l=0.02,
            text_density=0.25,
            bg_ratio=0.88,
        )
        active_audio_pids = set()
        is_video, score, details = evaluate_video_score(
            win, visuals, active_audio_pids=active_audio_pids
        )
        self.assertFalse(is_video)
        self.assertEqual(score, 0.0)

    def test_fullscreen_presentation(self):
        win = Window(
            title="Fullscreen Media Player",
            address="0xbbbb",
            x=0,
            y=0,
            width=1920,
            height=1080,
            pid=8888,
            inhibiting_idle=True,
            fullscreen=True,
        )
        visuals = WindowVisuals(
            text_l=0.7,
            bg_l=0.2,
            text_density=0.05,
            bg_ratio=0.30,
        )
        active_audio_pids = {8888}
        is_video, score, details = evaluate_video_score(
            win, visuals, active_audio_pids=active_audio_pids
        )
        self.assertTrue(is_video)
        # 0.35 (idle) + 0.35 (audio) + 0.25 (visual) + 0.15 (fullscreen) = 1.0
        self.assertEqual(score, 1.0)
        self.assertTrue(details["fullscreen"])


class TestSettingsValidation(unittest.TestCase):
    def test_update_video_opacity_valid(self):
        ok, msg, cfg = update_setting("video_opacity", "0.92")
        self.assertTrue(ok)
        self.assertEqual(cfg.video_opacity, 0.92)

    def test_update_video_opacity_out_of_bounds(self):
        ok, msg, cfg = update_setting("video_opacity", "1.5")
        self.assertFalse(ok)
        self.assertIn("exceeds maximum", msg)

        ok, msg, cfg = update_setting("video_opacity", "-0.1")
        self.assertFalse(ok)
        self.assertIn("below minimum", msg)

    def test_update_target_contrast_valid(self):
        ok, msg, cfg = update_setting("target_contrast", "7.0")
        self.assertTrue(ok)
        self.assertEqual(cfg.target_contrast, 7.0)

    def test_update_unknown_setting(self):
        ok, msg, cfg = update_setting("invalid_setting_key", "123")
        self.assertFalse(ok)
        self.assertIn("Unknown setting", msg)


if __name__ == "__main__":
    unittest.main()
