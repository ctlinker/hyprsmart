from dataclasses import dataclass, field, asdict
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
from typing import Any
import yaml

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hyprsmart"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
BLACKLIST_FILE = CONFIG_DIR / "blacklist.yaml"
SYSTEM_BLACKLIST_FILE = Path("/etc/hyprsmart/blacklist.yaml")

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

SENSITIVE_TITLE_KEYWORDS: tuple[str, ...] = (
    "private browsing",
    "incognito",
    "authentication required",
    "unlock keyring",
    "pinentry",
    "enter password",
)

def get_blacklist_path() -> Path:
    env_override = os.environ.get("HYPRSMART_BLACKLIST_FILE")
    if env_override:
        return Path(env_override)
    if SYSTEM_BLACKLIST_FILE.exists():
        return SYSTEM_BLACKLIST_FILE
    return BLACKLIST_FILE


def find_escalation_tool() -> str | None:
    for tool in ("pkexec", "sudo", "doas"):
        path = shutil.which(tool)
        if path:
            return path
    return None


def _write_blacklist_direct(target_path: Path, content: str) -> tuple[bool, str]:
    try:
        target_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if target_path.exists():
            try:
                target_path.chmod(0o600)
            except OSError:
                pass

        tmp_file = target_path.with_suffix(".tmp")
        tmp_file.write_text(content, encoding="utf-8")
        try:
            tmp_file.chmod(0o444)
        except OSError:
            pass
        tmp_file.replace(target_path)
        try:
            target_path.chmod(0o444)
        except OSError:
            pass
        return True, f"Updated {target_path} (mode 0444, read-only)"
    except Exception as e:
        return False, f"Failed to write blacklist directly: {e}"


def save_blacklist(
    classes: list[str],
    target_path: Path | None = None,
    escalation_tool: str | None = None,
    force_direct: bool = False,
) -> tuple[bool, str]:
    if target_path is None:
        target_path = get_blacklist_path()
    target_path = Path(target_path).resolve()

    clean_classes = sorted(list({str(c).strip().lower() for c in classes if str(c).strip()}))

    yaml_header = (
        "# HyprSmart Privacy Shield - Sensitive Window Classes Blacklist\n"
        "# This file is protected and read-only (chmod 0444).\n"
        "# Unprivileged processes cannot silently modify this file.\n"
        "# To modify: run 'hyprsmart blacklist add <class>' or 'hyprsmart blacklist remove <class>'\n"
        "# Shielded windows are forced to full opacity (1.0) and never captured via grim.\n"
    )
    payload = {"sensitive_classes": clean_classes}
    content = yaml_header + yaml.dump(payload, sort_keys=False)

    if force_direct or os.environ.get("HYPRSMART_NO_ESCALATE") == "1":
        return _write_blacklist_direct(target_path, content)

    tool = escalation_tool if escalation_tool is not None else find_escalation_tool()
    if not tool:
        return _write_blacklist_direct(target_path, content)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, prefix="hyprsmart_bl_", suffix=".yaml") as tf:
            tf.write(content)
            tmp_path = Path(tf.name)
        try:
            tmp_path.chmod(0o644)
        except OSError:
            pass

        cmd = [tool, "install", "-m", "0444", "-D", str(tmp_path), str(target_path)]
        try:
            subprocess.run(cmd, check=True)
            return True, f"Successfully updated and locked {target_path} via {tool} (mode 0444)"
        except subprocess.CalledProcessError as e:
            if tool.endswith("pkexec"):
                sudo_tool = shutil.which("sudo")
                if sudo_tool:
                    try:
                        sudo_cmd = [sudo_tool, "install", "-m", "0444", "-D", str(tmp_path), str(target_path)]
                        subprocess.run(sudo_cmd, check=True)
                        return True, f"Successfully updated and locked {target_path} via {sudo_tool} (mode 0444)"
                    except Exception as sudo_err:
                        return False, f"Privilege escalation failed (Polkit exit {e.returncode}, sudo error: {sudo_err})"
            return False, f"Privilege escalation via {tool} failed (exit code {e.returncode})"
    except Exception as e:
        return False, f"Error preparing escalation write: {e}"
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def load_blacklist() -> list[str]:
    path = get_blacklist_path()
    if not path.exists():
        if path == BLACKLIST_FILE:
            try:
                save_blacklist(DEFAULT_SENSITIVE_CLASSES, target_path=path, force_direct=True)
            except Exception as e:
                print(f"[WARN] Failed to auto-create default blacklist at {path}: {e}")
        return list(DEFAULT_SENSITIVE_CLASSES)

    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        raw_list = None
        if isinstance(data, dict):
            raw_list = data.get("sensitive_classes")
        elif isinstance(data, list):
            raw_list = data

        if isinstance(raw_list, list):
            return sorted(list({str(c).strip().lower() for c in raw_list if str(c).strip()}))
    except Exception as e:
        print(f"[WARN] Failed to load blacklist from {path}: {e}")

    return list(DEFAULT_SENSITIVE_CLASSES)


def get_blacklist_info() -> dict[str, Any]:
    path = get_blacklist_path()
    exists = path.exists()
    mode_str = "missing"
    is_readonly = False
    owner_str = "unknown"
    if exists:
        try:
            st = path.stat()
            mode = st.st_mode & 0o777
            mode_str = oct(mode)
            is_readonly = (mode & 0o222) == 0
            try:
                import pwd
                import grp
                user = pwd.getpwuid(st.st_uid).pw_name
                group = grp.getgrgid(st.st_gid).gr_name
                owner_str = f"{user}:{group}"
            except Exception:
                owner_str = f"{st.st_uid}:{st.st_gid}"
        except Exception:
            pass

    return {
        "path": path,
        "exists": exists,
        "is_system": path == SYSTEM_BLACKLIST_FILE,
        "mode": mode_str,
        "is_readonly": is_readonly,
        "owner": owner_str,
        "escalation_tool": find_escalation_tool(),
        "classes": load_blacklist(),
        "keywords": SENSITIVE_TITLE_KEYWORDS,
    }


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

    if any(kw in title_lower for kw in SENSITIVE_TITLE_KEYWORDS):
        return True

    return False


_CURRENT_CONFIG: HyprsmartConfig | None = None
_CONFIG_MTIME: float | None = None
_BLACKLIST_MTIME: float | None = None

def load_config() -> HyprsmartConfig:
    global _CURRENT_CONFIG, _CONFIG_MTIME, _BLACKLIST_MTIME
    bl_path = get_blacklist_path()
    try:
        if bl_path.exists():
            _BLACKLIST_MTIME = bl_path.stat().st_mtime
        else:
            _BLACKLIST_MTIME = None
    except OSError:
        _BLACKLIST_MTIME = None

    sensitive_classes = load_blacklist()

    if not CONFIG_FILE.exists():
        _CURRENT_CONFIG = HyprsmartConfig(sensitive_classes=sensitive_classes)
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
            sensitive_classes=sensitive_classes,
        )
    except Exception as e:
        print(f"[WARN] Failed to load config from {CONFIG_FILE}: {e}")
        _CURRENT_CONFIG = HyprsmartConfig(sensitive_classes=sensitive_classes)

    return _CURRENT_CONFIG

def get_current_config() -> HyprsmartConfig:
    global _CURRENT_CONFIG, _CONFIG_MTIME, _BLACKLIST_MTIME
    if _CURRENT_CONFIG is None:
        return load_config()
    try:
        reload_needed = False
        if CONFIG_FILE.exists():
            mtime = CONFIG_FILE.stat().st_mtime
            if _CONFIG_MTIME is None or mtime != _CONFIG_MTIME:
                reload_needed = True
        bl_path = get_blacklist_path()
        if bl_path.exists():
            b_mtime = bl_path.stat().st_mtime
            if _BLACKLIST_MTIME is None or b_mtime != _BLACKLIST_MTIME:
                reload_needed = True
        elif _BLACKLIST_MTIME is not None:
            reload_needed = True
        if reload_needed:
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
        "description": "Shielded window classes (stored in read-only blacklist.yaml, prefer 'hyprsmart blacklist')",
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
            if key == "sensitive_classes":
                ok, msg = save_blacklist(val, force_direct=(os.environ.get("HYPRSMART_NO_ESCALATE") == "1"))
                if not ok:
                    return False, msg, cfg
                cfg.sensitive_classes = val
                return True, f"Setting '{key}' set to {val} ({msg})", cfg
            setattr(cfg, key, val)
    except ValueError:
        return False, f"Invalid value '{raw_value}' for setting '{key}'. Expected {expected_type.__name__}.", cfg

    save_config(cfg)
    return True, f"Setting '{key}' set to {getattr(cfg, key)}", cfg

