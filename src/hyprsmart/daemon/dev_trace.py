from dataclasses import asdict
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
from threading import Lock
import time
from typing import Any

import numpy as np
from PIL import Image

from hyprsmart.config import HyprsmartConfig
from hyprsmart.opacity.backdrop import Backdrop, _luminance, compute_sobel_energy
from hyprsmart.opacity.compute import _ratio
from hyprsmart.opacity.win_col import WindowVisuals
from hyprsmart.primitive import Monitor, Window, capture_window

DEV_MODE_ENABLED: bool = False
_DEV_LOCK = Lock()
_SEQ_COUNTER: int = 0


def set_dev_mode(enabled: bool) -> None:
    global DEV_MODE_ENABLED
    with _DEV_LOCK:
        DEV_MODE_ENABLED = bool(enabled)


def is_dev_mode() -> bool:
    with _DEV_LOCK:
        return DEV_MODE_ENABLED


def get_dev_captures_dir() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hyprsmart" / "dev_captures"
    base.mkdir(parents=True, exist_ok=True)
    return base


def extract_raw_capture_diagnostics(img_bytes: bytes | None) -> dict[str, Any] | None:
    """Extract raw (pre-unblending) visual statistics from captured PNG bytes for dev inspection."""
    if not img_bytes:
        return None
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        orig_w, orig_h = img.size
        img.thumbnail((512, 512))
        thumb_w, thumb_h = img.size
        rgb = np.asarray(img)

        q = (rgb >> 4).reshape(-1, 3).astype(np.int32)
        packed = (q[:, 0] << 8) | (q[:, 1] << 4) | q[:, 2]
        vals, counts = np.unique(packed, return_counts=True)
        top_idx = int(counts.argmax())
        top = int(vals[top_idx])
        raw_bg_ratio = float(counts[top_idx] / len(packed))

        bg_rgb = [int((top >> 8) & 15) * 16 + 8, int((top >> 4) & 15) * 16 + 8, int(top & 15) * 16 + 8]
        raw_bg_l = float(_luminance(np.array(bg_rgb, dtype=np.float32)))

        lum = _luminance(rgb.astype(np.float32))
        non_bg = lum[np.abs(lum - raw_bg_l) > 0.05]
        if len(non_bg) > 30:
            raw_text_l = float(np.percentile(non_bg, 95 if raw_bg_l < 0.5 else 5))
            text_method = "non_bg_p95_or_p5"
        else:
            raw_text_l = float(np.percentile(lum, 99.5 if raw_bg_l < 0.5 else 0.5))
            text_method = "fallback_lum_p99.5_or_p0.5"

        grad = compute_sobel_energy(lum)
        raw_text_density = float(np.mean(grad > 0.08))

        return {
            "original_size": [orig_w, orig_h],
            "thumbnail_size": [thumb_w, thumb_h],
            "dominant_bin_rgb": bg_rgb,
            "raw_bg_l": round(raw_bg_l, 4),
            "raw_text_l": round(raw_text_l, 4),
            "raw_bg_ratio": round(raw_bg_ratio, 4),
            "raw_text_density": round(raw_text_density, 4),
            "non_bg_pixel_count": int(len(non_bg)),
            "total_thumbnail_pixels": int(len(packed)),
            "unique_12bit_bins": int(len(vals)),
            "text_extraction_method": text_method,
        }
    except Exception as e:
        return {"error": str(e)}


def compute_solver_breakdown(
    visuals: WindowVisuals,
    backdrop: Backdrop | None,
    cfg: HyprsmartConfig,
    before_alpha: float,
    after_alpha: float,
    is_video: bool,
    raw_diag: dict[str, Any] | None = None,
    mon: Monitor | None = None,
) -> dict[str, Any]:
    intrinsic_cr = _ratio(visuals.text_l, visuals.bg_l)
    anomalies: list[str] = []

    if intrinsic_cr < cfg.target_contrast:
        anomalies.append(
            f"intrinsic_contrast_below_target: window text_l ({visuals.text_l:.4f}) vs bg_l ({visuals.bg_l:.4f}) "
            f"has max contrast {intrinsic_cr:.2f}:1 at alpha=1.0, below target_contrast={cfg.target_contrast:.2f}"
        )
    if intrinsic_cr < 3.0:
        anomalies.append(
            f"unachievable_wcag_contrast: intrinsic contrast is only {intrinsic_cr:.2f}:1 (< 3.0), "
            "forcing solver to return 1.0 (opaque)"
        )
    if before_alpha < 0.99 and visuals.bg_ratio < 0.45:
        anomalies.append(
            f"transparent_capture_bg_ratio_drop: captured while window was transparent (before_alpha={before_alpha:.2f}), "
            f"bg_ratio={visuals.bg_ratio:.2f} likely fragmented across 12-bit bins by wallpaper bleed-through"
        )
    if mon is not None and abs(mon.scale - 1.0) > 0.01:
        anomalies.append(
            f"monitor_scale_mismatch: monitor scale is {mon.scale} != 1.0; window coordinates are logical "
            "while wallpaper luminance map uses physical resolution"
        )

    if backdrop is None:
        return {
            "mode": "video_override" if is_video else "no_backdrop",
            "intrinsic_window_contrast": round(intrinsic_cr, 4),
            "anomalies_detected": anomalies,
        }

    clutter_adj = max(-0.20, min(1.0, (backdrop.edge_energy - 0.020) * 8.0))
    bg_weight = max(0.0, min(1.0, (visuals.bg_ratio - 0.50) / 0.25))
    sparse_weight = max(0.0, min(1.0, (0.18 - visuals.text_density) / 0.12))
    sparse_relax_amount = 0.30 * bg_weight * sparse_weight
    effective_target = max(2.8, cfg.target_contrast + clutter_adj - sparse_relax_amount)

    edge_calm = max(0.0, min(1.0, (0.10 - backdrop.edge_energy) / 0.04))
    bg_dom = max(0.0, min(1.0, (visuals.bg_ratio - 0.45) / 0.20))
    w_trim = edge_calm * bg_dom

    sample_low = w_trim * backdrop.p15 + (1.0 - w_trim) * backdrop.p5
    sample_high = w_trim * backdrop.p85 + (1.0 - w_trim) * backdrop.p95
    samples = (sample_low, sample_high)
    sample_mode = f"continuous_blend(w_trim={w_trim:.2f})"

    if visuals.bg_l < 0.5:
        cal_text_l = min(0.60, max(visuals.bg_l + 0.42, 0.48, 0.45 * visuals.text_l + 0.55 * 0.52))
        raw_bleed = 0.35 * backdrop.median + 0.65 * sample_high
        disturb_l = min(
            1.0,
            (max(0.0, raw_bleed) ** 0.58)
            + 0.45 * backdrop.std
            + 1.10 * backdrop.edge_energy,
        )
        worst_l = min(1.0, (max(0.0, backdrop.p95) ** 0.58) + 0.50 * backdrop.std)
    else:
        cal_text_l = max(0.01, min(visuals.bg_l - 0.45, 0.05, 0.45 * visuals.text_l + 0.55 * 0.04))
        raw_bleed = 0.35 * backdrop.median + 0.65 * sample_low
        dark_pull = (1.0 - max(0.0, min(1.0, raw_bleed))) ** 0.58
        disturb_l = max(
            0.0,
            1.0 - dark_pull - 0.45 * backdrop.std - 1.10 * backdrop.edge_energy,
        )
        worst_l = max(0.0, 1.0 - ((1.0 - max(0.0, min(1.0, backdrop.p5))) ** 0.58) - 0.50 * backdrop.std)

    r_opaque = _ratio(cal_text_l, visuals.bg_l)
    scale_norm = max(1.0, 10.5 / max(1.0, r_opaque))
    required_worst = max(2.5, effective_target * 0.68)

    def _eval_at(a: float) -> dict[str, float]:
        r_prim = _ratio(cal_text_l, a * visuals.bg_l + (1.0 - a) * disturb_l) * scale_norm
        r_w = _ratio(cal_text_l, a * visuals.bg_l + (1.0 - a) * worst_l) * scale_norm
        return {
            "alpha": round(a, 2),
            "r_primary": round(float(r_prim), 4),
            "r_worst": round(float(r_w), 4),
            "passes_primary_target": bool(r_prim >= effective_target),
            "passes_worst_floor": bool(r_w >= required_worst),
        }

    return {
        "mode": "video_override" if is_video else "wcag_solver",
        "intrinsic_window_contrast": round(float(intrinsic_cr), 4),
        "calibrated_text_l": round(float(cal_text_l), 4),
        "disturb_l": round(float(disturb_l), 4),
        "worst_l": round(float(worst_l), 4),
        "scale_norm": round(float(scale_norm), 4),
        "clutter_adjustment": round(float(clutter_adj), 4),
        "effective_target_contrast": round(float(effective_target), 4),
        "required_worst_contrast": round(float(required_worst), 4),
        "sparse_relaxation_amount": round(float(sparse_relax_amount), 4),
        "backdrop_sample_mode": sample_mode,
        "backdrop_samples": [round(float(samples[0]), 4), round(float(samples[1]), 4)],
        "eval_before_alpha": _eval_at(before_alpha),
        "eval_after_alpha": _eval_at(after_alpha),
        "anomalies_detected": anomalies,
    }


def save_dev_decision_bundle(
    *,
    win: Window,
    mon: Monitor | None,
    cfg: HyprsmartConfig,
    wall_path: str | None,
    visuals: WindowVisuals,
    backdrop: Backdrop | None,
    before_alpha: float,
    after_alpha: float,
    applied_ipc: bool,
    from_cache: bool,
    is_preload: bool,
    is_video: bool,
    video_score: float,
    video_signals: dict[str, Any],
    before_img_bytes: bytes | None,
    after_img_bytes: bytes | None,
    class_profile_before: WindowVisuals | None = None,
    class_profile_after: WindowVisuals | None = None,
) -> Path | None:
    """
    Save before.png, after.png, and metadata.json for a single opacity decision.
    """
    global _SEQ_COUNTER
    with _DEV_LOCK:
        _SEQ_COUNTER += 1
        seq = _SEQ_COUNTER

    now = datetime.now(timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S_%f")
    safe_cls = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in (win.window_class or "unknown"))
    safe_addr = win.address.replace("0x", "")

    bundle_dir = get_dev_captures_dir() / f"{ts_str}_{seq:04d}_{safe_cls}_{safe_addr}"
    try:
        bundle_dir.mkdir(parents=True, exist_ok=True)

        before_path = bundle_dir / "before.png"
        after_path = bundle_dir / "after.png"
        meta_path = bundle_dir / "metadata.json"

        # If before_img_bytes wasn't provided (e.g. cache hit), try capturing or note missing
        if before_img_bytes:
            before_path.write_bytes(before_img_bytes)

        if after_img_bytes:
            after_path.write_bytes(after_img_bytes)
        elif before_img_bytes and not applied_ipc:
            # Opacity was unchanged (skipped IPC due to diff threshold), so after is identical to before
            after_path.write_bytes(before_img_bytes)

        raw_diag = extract_raw_capture_diagnostics(before_img_bytes)
        solver_info = compute_solver_breakdown(
            visuals=visuals,
            backdrop=backdrop,
            cfg=cfg,
            before_alpha=before_alpha,
            after_alpha=after_alpha,
            is_video=is_video,
            raw_diag=raw_diag,
            mon=mon,
        )

        decision_source = "preload" if is_preload else ("cache_hit" if from_cache else "fresh_capture")

        metadata = {
            "sequence_id": seq,
            "timestamp_epoch": time.time(),
            "timestamp_iso": now.isoformat(),
            "decision_source": decision_source,
            "files": {
                "before_png": str(before_path) if before_path.exists() else None,
                "after_png": str(after_path) if after_path.exists() else None,
                "metadata_json": str(meta_path),
            },
            "window": {
                "address": win.address,
                "title": win.title,
                "window_class": win.window_class,
                "x": win.x,
                "y": win.y,
                "width": win.width,
                "height": win.height,
                "pid": win.pid,
                "inhibiting_idle": win.inhibiting_idle,
                "fullscreen": win.fullscreen,
                "monitor_id": win.monitor_id,
            },
            "monitor": asdict(mon) if mon is not None else None,
            "wallpaper_path": wall_path,
            "config": {
                "target_contrast": cfg.target_contrast,
                "floor_opacity": cfg.floor_opacity,
                "video_opacity": cfg.video_opacity,
                "debounce_interval": cfg.debounce_interval,
            },
            "opacity_decision": {
                "before_alpha": round(float(before_alpha), 4),
                "after_alpha": round(float(after_alpha), 4),
                "alpha_diff": round(float(abs(after_alpha - before_alpha)), 4),
                "applied_to_hyprland": applied_ipc,
                "from_cache": from_cache,
                "is_preload": is_preload,
            },
            "visuals": {
                "unblended": {
                    "text_l": round(float(visuals.text_l), 4),
                    "bg_l": round(float(visuals.bg_l), 4),
                    "text_density": round(float(visuals.text_density), 4),
                    "bg_ratio": round(float(visuals.bg_ratio), 4),
                },
                "raw_captured": raw_diag,
                "class_profile_before": asdict(class_profile_before) if class_profile_before else None,
                "class_profile_after": asdict(class_profile_after) if class_profile_after else None,
            },
            "backdrop": {
                "p5": round(float(backdrop.p5), 4),
                "p15": round(float(backdrop.p15), 4),
                "median": round(float(backdrop.median), 4),
                "p85": round(float(backdrop.p85), 4),
                "p95": round(float(backdrop.p95), 4),
                "std": round(float(backdrop.std), 4),
                "edge_energy": round(float(backdrop.edge_energy), 4),
            } if backdrop is not None else None,
            "video_detection": {
                "is_video": is_video,
                "score": video_score,
                "signals": video_signals,
            },
            "solver_breakdown": solver_info,
        }

        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[DEV-TRACE] Saved decision #{seq} (before.png, after.png, metadata.json) -> {bundle_dir}")
        return bundle_dir
    except Exception as e:
        print(f"[WARN] Failed to save dev decision bundle: {e}")
        return None
