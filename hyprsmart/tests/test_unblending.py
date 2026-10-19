import unittest
from hyprsmart.opacity.win_col import WindowVisuals, unblend_luminance
from hyprsmart.daemon.cache import (
    CLASS_PROFILES,
    cache_clear,
    get_class_profile,
    update_class_profile,
)


class TestOpticalUnblending(unittest.TestCase):
    def setUp(self):
        cache_clear()

    def test_unblend_at_full_opacity(self):
        # When window is 1.0, captured luminance is already pure
        pure = unblend_luminance(0.42, 1.0, backdrop_l=0.9)
        self.assertAlmostEqual(pure, 0.42, places=4)

    def test_unblend_synthetic_blend(self):
        # Ground truth:
        # Window pure background = 0.10 (dark terminal)
        # Wallpaper underneath = 0.80 (bright wallpaper)
        # Opacity = 0.70
        # Composited: 0.70 * 0.10 + 0.30 * 0.80 = 0.07 + 0.24 = 0.31
        composite_l = 0.70 * 0.10 + 0.30 * 0.80

        recovered_l = unblend_luminance(composite_l, alpha=0.70, backdrop_l=0.80)
        self.assertAlmostEqual(recovered_l, 0.10, places=4)

    def test_unblend_white_page_on_dark_wallpaper(self):
        # Ground truth:
        # Window pure background = 0.95 (bright webpage)
        # Wallpaper underneath = 0.05 (dark wallpaper)
        # Opacity = 0.60
        # Composited: 0.60 * 0.95 + 0.40 * 0.05 = 0.57 + 0.02 = 0.59
        composite_l = 0.60 * 0.95 + 0.40 * 0.05

        recovered_l = unblend_luminance(composite_l, alpha=0.60, backdrop_l=0.05)
        self.assertAlmostEqual(recovered_l, 0.95, places=4)

    def test_unblend_with_class_regularization(self):
        # When alpha is lower (e.g. 0.40), class reference regularizes the result
        class_ref_l = 0.10
        noisy_composite = 0.40 * 0.15 + 0.60 * 0.80  # 0.06 + 0.48 = 0.54

        regularized = unblend_luminance(
            noisy_composite,
            alpha=0.40,
            backdrop_l=0.80,
            class_ref_l=class_ref_l,
        )
        # Should be between the unblended 0.15 and class_ref 0.10
        self.assertTrue(0.08 <= regularized <= 0.15)

    def test_class_profile_ema_updating(self):
        vis1 = WindowVisuals(text_l=0.90, bg_l=0.10, text_density=0.20, bg_ratio=0.80)
        update_class_profile("alacritty", vis1)

        prof = get_class_profile("alacritty")
        self.assertIsNotNone(prof)
        self.assertAlmostEqual(prof.bg_l, 0.10, places=3)

        # Update with second observation (0.20)
        vis2 = WindowVisuals(text_l=0.85, bg_l=0.20, text_density=0.15, bg_ratio=0.75)
        update_class_profile("alacritty", vis2)

        prof2 = get_class_profile("alacritty")
        # 0.7 * 0.10 + 0.3 * 0.20 = 0.07 + 0.06 = 0.13
        self.assertAlmostEqual(prof2.bg_l, 0.13, places=3)


if __name__ == "__main__":
    unittest.main()
