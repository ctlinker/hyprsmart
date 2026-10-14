import json
import os
import subprocess
import time
from typing import Any

from hyprsmart.opacity.win_col import WindowVisuals
from hyprsmart.primitive.window import Window

_AUDIO_CACHE: tuple[float, set[int]] | None = None
_AUDIO_CACHE_TTL = 0.5  # seconds


def get_active_audio_pids(force_refresh: bool = False) -> set[int]:
    """Return the set of PIDs actively playing audio via PulseAudio / PipeWire."""
    global _AUDIO_CACHE
    now = time.time()
    if not force_refresh and _AUDIO_CACHE is not None:
        cache_time, cached_pids = _AUDIO_CACHE
        if now - cache_time < _AUDIO_CACHE_TTL:
            return cached_pids

    active_pids: set[int] = set()

    # Try JSON output first (PipeWire / PulseAudio pactl >= 16)
    try:
        res = subprocess.run(
            ["pactl", "--format=json", "list", "sink-inputs"],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if res.returncode == 0 and res.stdout.strip():
            inputs = json.loads(res.stdout)
            if isinstance(inputs, list):
                for item in inputs:
                    if not isinstance(item, dict):
                        continue
                    # Check mute / corked state
                    if item.get("mute") is True:
                        continue
                    if item.get("corked") is True:
                        continue
                    state = str(item.get("state", "")).upper()
                    if state in ("CORKED", "PAUSED"):
                        continue

                    props = item.get("properties", {})
                    if props.get("corked") in ("true", "1", True):
                        continue

                    pid_str = props.get("application.process.id")
                    if pid_str is not None:
                        try:
                            active_pids.add(int(pid_str))
                        except (ValueError, TypeError):
                            pass

                _AUDIO_CACHE = (now, active_pids)
                return active_pids
    except Exception:
        pass

    # Fallback: parse plain text pactl output if JSON fails or older pactl
    try:
        res = subprocess.run(
            ["pactl", "list", "sink-inputs"],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if res.returncode == 0:
            current_pid = None
            is_corked_or_muted = False
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.startswith("Sink Input #"):
                    if current_pid is not None and not is_corked_or_muted:
                        active_pids.add(current_pid)
                    current_pid = None
                    is_corked_or_muted = False
                elif "Mute: yes" in line or "Corked: yes" in line:
                    is_corked_or_muted = True
                elif "application.process.id =" in line:
                    parts = line.split("=")
                    if len(parts) >= 2:
                        val = parts[1].strip().strip('"')
                        try:
                            current_pid = int(val)
                        except ValueError:
                            pass
            if current_pid is not None and not is_corked_or_muted:
                active_pids.add(current_pid)
    except Exception:
        pass

    _AUDIO_CACHE = (now, active_pids)
    return active_pids


def is_pid_emitting_audio(target_pid: int, active_audio_pids: set[int] | None = None) -> bool:
    """Check if target_pid or any of its subprocess descendants is actively outputting audio."""
    if target_pid <= 0:
        return False

    if active_audio_pids is None:
        active_audio_pids = get_active_audio_pids()

    if target_pid in active_audio_pids:
        return True

    # Traverse process tree: audio sinks are often created by child renderer processes
    # whose ancestor is the target window PID.
    for audio_pid in active_audio_pids:
        curr = audio_pid
        visited = set()
        while curr > 1 and curr not in visited:
            visited.add(curr)
            try:
                status_path = f"/proc/{curr}/status"
                if not os.path.exists(status_path):
                    break
                ppid = 0
                with open(status_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("PPid:"):
                            ppid = int(line.split()[1])
                            break
                if ppid == target_pid:
                    return True
                curr = ppid
            except (OSError, ValueError):
                break

    return False


def evaluate_video_score(
    win: Window,
    visuals: WindowVisuals | None = None,
    active_audio_pids: set[int] | None = None,
) -> tuple[bool, float, dict[str, Any]]:
    """
    Multi-signal video detection heuristic.

    Signals and Weights:
      - idle_inhibit (0.35): Wayland idle-inhibitor active (browser / media player).
      - audio_active (0.35): Window or child PID playing non-corked audio stream.
      - visual_video (0.25): Window visual characteristics match video content.
      - fullscreen   (0.15): Window is in fullscreen mode.

    Decision Rule:
      Score >= 0.55 -> is_video = True
    """
    signals: dict[str, Any] = {
        "idle_inhibit": False,
        "audio_active": False,
        "visual_video": False,
        "fullscreen": False,
    }

    score = 0.0

    # 1. Idle inhibitor (+0.35)
    if win.inhibiting_idle:
        signals["idle_inhibit"] = True
        score += 0.35

    # 2. Audio playback (+0.35)
    if win.pid > 0 and is_pid_emitting_audio(win.pid, active_audio_pids):
        signals["audio_active"] = True
        score += 0.35

    # 3. Visual characteristics (+0.25)
    if visuals is not None:
        # Video frames typically lack large uniform solid backgrounds
        # and maintain lower text density than text documents / source code.
        is_visual = visuals.bg_ratio < 0.40 and visuals.text_density < 0.20
        if is_visual:
            signals["visual_video"] = True
            score += 0.25

    # 4. Fullscreen (+0.15)
    if win.fullscreen:
        signals["fullscreen"] = True
        score += 0.15

    score = round(min(1.0, score), 3)
    is_video = score >= 0.55

    signals["score"] = score
    signals["is_video"] = is_video
    return is_video, score, signals
