from dataclasses import dataclass, field, asdict
from pathlib import Path
import os
from typing import Any
import yaml

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hyprsmart"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

DEFAULT_SENSITIVE_CLASSES: list[str] = [
    "keepassxc",
    "org.keepassxc.keepassxc",
    "1password",
    "bitwarden",
    "gcr-prompter",
    "polkit-gnome-authentication-agent-1",
    "pinentry",
    "pinentry-qt",
    "pinentry-gtk-2",
]

@dataclass
class HyprsmartConfig:
    monitors: dict[str, str] = field(default_factory=dict)
    default_wallpaper: str | None = None
    target_contrast: float = 6.0
    floor_opacity: float = 0.5
    video_opacity: float = 1.0
    debounce_interval: float = 0.1
    reeval_max_ticks: int = 11
    reeval_stable_ticks: int = 8
    reeval_interval: float = 1.0
    sensitive_classes: list[str] = field(default_factory=lambda: list(DEFAULT_SENSITIVE_CLASSES))

    def get_wallpaper(self, mon_name: str, mon_id: int | str | None = None) -> str | None:
        """Find wallpaper by monitor id or monitor name, then fallback to default."""
        if mon_id is not None and str(mon_id) in self.monitors:
            return self.monitors[str(mon_id)]
        if mon_name in self.monitors:
            return self.monitors[mon_name]
        return self.default_wallpaper


def is_sensitive_window(win: Any, cfg: HyprsmartConfig | None = None) -> bool:
    """
    Check if a window is marked sensitive or private (password managers, auth prompts, incognito).
    Sensitive windows must never be captured via grim, probed progressively, or traced.
    """
    if win is None:
        return False

    if cfg is None:
        cfg = get_current_config()

    w_cls = getattr(win, "window_class", "") or ""
    w_title = getattr(win, "title", "") or ""

    cls_lower = str(w_cls).strip().lower()
    title_lower = str(w_title).strip().lower()

    sensitive_set = {str(c).strip().lower() for c in cfg.sensitive_classes}
    if cls_lower in sensitive_set:
        return True
    for sc in sensitive_set:
        if sc and sc in cls_lower:
            return True

    sensitive_title_keywords = (
        "private browsing",
        "incognito",
        "authentication required",
        "unlock keyring",
        "pinentry",
        "enter password",
    )
    if any(kw in title_lower for kw in sensitive_title_keywords):
        return True

    return False


_CURRENT_CONFIG: HyprsmartConfig | None = None
_CONFIG_MTIME: float | None = None

def load_config() -> HyprsmartConfig:
    global _CURRENT_CONFIG, _CONFIG_MTIME
    if not CONFIG_FILE.exists():
        _CURRENT_CONFIG = HyprsmartConfig()
        _CONFIG_MTIME = None
        return _CURRENT_CONFIG

    try:
        _CONFIG_MTIME = CONFIG_FILE.stat().st_mtime
        data = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
        raw_sensitive = data.get("sensitive_classes")
        if isinstance(raw_sensitive, list):
            sensitive_classes = [str(c).strip().lower() for c in raw_sensitive if str(c).strip()]
        else:
            sensitive_classes = list(DEFAULT_SENSITIVE_CLASSES)

        _CURRENT_CONFIG = HyprsmartConfig(
            monitors={str(k): str(v) for k, v in data.get("monitors", {}).items()},
            default_wallpaper=data.get("default_wallpaper"),
            target_contrast=float(data.get("target_contrast", 6.0)),
            floor_opacity=float(data.get("floor_opacity", 0.5)),
            video_opacity=float(data.get("video_opacity", 1.0)),
            debounce_interval=float(data.get("debounce_interval", 0.1)),
            reeval_max_ticks=int(data.get("reeval_max_ticks", 11)),
            reeval_stable_ticks=int(data.get("reeval_stable_ticks", 8)),
            reeval_interval=float(data.get("reeval_interval", 1.0)),
            sensitive_classes=sensitive_classes,
        )
    except Exception as e:
        print(f"[WARN] Failed to load config from {CONFIG_FILE}: {e}")
        _CURRENT_CONFIG = HyprsmartConfig()

    return _CURRENT_CONFIG

def get_current_config() -> HyprsmartConfig:
    global _CURRENT_CONFIG, _CONFIG_MTIME
    if _CURRENT_CONFIG is None:
        return load_config()
    try:
        if CONFIG_FILE.exists():
            mtime = CONFIG_FILE.stat().st_mtime
            if _CONFIG_MTIME is None or mtime != _CONFIG_MTIME:
                return load_config()
    except OSError:
        pass
    return _CURRENT_CONFIG

def save_config(cfg: HyprsmartConfig) -> None:
    global _CURRENT_CONFIG, _CONFIG_MTIME
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass

    data = {
        "monitors": cfg.monitors,
        "default_wallpaper": cfg.default_wallpaper,
        "target_contrast": cfg.target_contrast,
        "floor_opacity": cfg.floor_opacity,
        "video_opacity": cfg.video_opacity,
        "debounce_interval": cfg.debounce_interval,
        "reeval_max_ticks": cfg.reeval_max_ticks,
        "reeval_stable_ticks": cfg.reeval_stable_ticks,
        "reeval_interval": cfg.reeval_interval,
        "sensitive_classes": cfg.sensitive_classes,
    }
    tmp_file = CONFIG_FILE.with_suffix(".tmp")
    tmp_file.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
    try:
        tmp_file.chmod(0o600)
    except OSError:
        pass
    tmp_file.replace(CONFIG_FILE)
    try:
        _CONFIG_MTIME = CONFIG_FILE.stat().st_mtime
    except OSError:
        pass
    _CURRENT_CONFIG = cfg

def set_monitor_wallpaper(mon_id_or_name: str, wall_path: str) -> HyprsmartConfig:
    cfg = get_current_config()
    p = Path(wall_path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Wallpaper path is not a regular file: {wall_path}")
    resolved_path = str(p)
    cfg.monitors[str(mon_id_or_name)] = resolved_path
    save_config(cfg)
    return cfg


SETTINGS_METADATA = {
    "video_opacity": {
        "type": float,
        "min": 0.0,
        "max": 1.0,
        "description": "Fixed opacity applied to detected video playback windows (0.0 to 1.0)",
    },
    "target_contrast": {
        "type": float,
        "min": 1.0,
        "max": 21.0,
        "description": "Target WCAG contrast ratio for text legibility (1.0 to 21.0)",
    },
    "floor_opacity": {
        "type": float,
        "min": 0.0,
        "max": 1.0,
        "description": "Minimum window transparency floor (0.0 to 1.0)",
    },
    "debounce_interval": {
        "type": float,
        "min": 0.0,
        "max": 10.0,
        "description": "Minimum interval in seconds between window recalculations",
    },
    "reeval_max_ticks": {
        "type": int,
        "min": 0,
        "max": 30,
        "description": "Maximum progressive 1s re-evaluation ticks after window change (0 to 30, default 11)",
    },
    "reeval_stable_ticks": {
        "type": int,
        "min": 1,
        "max": 30,
        "description": "Consecutive stable ticks before stopping progressive re-evaluation early (1 to 30, default 8)",
    },
    "reeval_interval": {
        "type": float,
        "min": 0.2,
        "max": 5.0,
        "description": "Interval in seconds between progressive re-evaluation ticks (0.2 to 5.0, default 1.0)",
    },
    "default_wallpaper": {
        "type": str,
        "min": None,
        "max": None,
        "description": "Default wallpaper path when no monitor-specific wallpaper is set",
    },
    "sensitive_classes": {
        "type": list,
        "min": None,
        "max": None,
        "description": "Comma-separated list of window classes shielded from screen capture (forced opaque)",
    },
}


def update_setting(key: str, raw_value: Any) -> tuple[bool, str, HyprsmartConfig]:
    """Validate and update a configuration setting, saving it to disk."""
    cfg = get_current_config()
    meta = SETTINGS_METADATA.get(key)
    if meta is None:
        valid_keys = ", ".join(SETTINGS_METADATA.keys())
        return False, f"Unknown setting '{key}'. Valid settings are: {valid_keys}", cfg

    expected_type = meta["type"]
    try:
        if expected_type in (float, int):
            val = expected_type(float(raw_value)) if expected_type is int and "." not in str(raw_value) else expected_type(raw_value)
            min_val = meta.get("min")
            max_val = meta.get("max")
            if min_val is not None and val < min_val:
                return False, f"Value {val} is below minimum allowed ({min_val}) for '{key}'", cfg
            if max_val is not None and val > max_val:
                return False, f"Value {val} exceeds maximum allowed ({max_val}) for '{key}'", cfg
            setattr(cfg, key, val)
        elif expected_type == str:
            val = str(raw_value).strip()
            if val.lower() in ("none", "null", ""):
                setattr(cfg, key, None)
            else:
                setattr(cfg, key, val)
        elif expected_type == list:
            if isinstance(raw_value, list):
                val = [str(c).strip().lower() for c in raw_value if str(c).strip()]
            else:
                raw_str = str(raw_value).strip()
                if raw_str.lower() in ("none", "null", "empty", "[]", ""):
                    val = []
                else:
                    val = [c.strip().lower() for c in raw_str.split(",") if c.strip()]
            setattr(cfg, key, val)
    except ValueError:
        return False, f"Invalid value '{raw_value}' for setting '{key}'. Expected {expected_type.__name__}.", cfg

    save_config(cfg)
    return True, f"Setting '{key}' set to {getattr(cfg, key)}", cfg

