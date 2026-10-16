from dataclasses import dataclass, field, asdict
from pathlib import Path
import os
import yaml

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hyprsmart"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

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

    def get_wallpaper(self, mon_name: str, mon_id: int | str | None = None) -> str | None:
        """Find wallpaper by monitor id or monitor name, then fallback to default."""
        if mon_id is not None and str(mon_id) in self.monitors:
            return self.monitors[str(mon_id)]
        if mon_name in self.monitors:
            return self.monitors[mon_name]
        return self.default_wallpaper

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
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
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
    }
    CONFIG_FILE.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
    try:
        _CONFIG_MTIME = CONFIG_FILE.stat().st_mtime
    except OSError:
        pass
    _CURRENT_CONFIG = cfg

def set_monitor_wallpaper(mon_id_or_name: str, wall_path: str) -> HyprsmartConfig:
    cfg = get_current_config()
    # Expand user/relative paths
    resolved_path = str(Path(wall_path).expanduser().resolve())
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
}


def update_setting(key: str, raw_value: str) -> tuple[bool, str, HyprsmartConfig]:
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
    except ValueError:
        return False, f"Invalid value '{raw_value}' for setting '{key}'. Expected {expected_type.__name__}.", cfg

    save_config(cfg)
    return True, f"Setting '{key}' set to {getattr(cfg, key)}", cfg

