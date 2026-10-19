<div align="center">

<img src="docs/assets/logo.png" alt="HyprSmart Logo" width="200" />

# HyprSmart
### *Adaptive window transparency for Hyprland*

[![Python](https://img.shields.io/badge/Python-3.14+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Hyprland](https://img.shields.io/badge/Hyprland-Wayland-00B4D8?style=flat-square)](https://hyprland.org)
[![WCAG 2.1](https://img.shields.io/badge/Accessibility-WCAG%202.1-4CAF50?style=flat-square)](https://www.w3.org/WAI/standards-guidelines/wcag/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)

*Effortless, intelligent transparency that automatically adapts to your wallpaper and window content.*

</div>

---

## Why HyprSmart?

Hyprland's window transparency looks fantastic—until a bright wallpaper makes your terminal or code editor impossible to read, or a dark video gets washed out. 

Constantly toggling opacity manually breaks your focus. **HyprSmart** runs quietly in the background as a lightweight daemon:
- It monitors the window you are working in.
- It samples the exact area of wallpaper behind that window.
- It dynamically computes and applies the ideal opacity level so that your text remains crisp and readable, adhering to **WCAG contrast standards**.
- When you watch a video or switch to sensitive apps, it adapts automatically.

No screen flashes. No heavy AI models. Just instant, beautiful, and readable transparency.

---

## Features at a Glance

- **Always Readable**: Guarantees optimal text contrast regardless of whether your wallpaper is light, dark, or cluttered.
- **Smart Video Detection**: Automatically keeps video players and streaming tabs opaque to preserve immersion and image quality.
- **Privacy Shield**: Password managers (Bitwarden, KeePassXC, 1Password) and private browsing windows are automatically kept fully opaque and shielded from screen sampling.
- **Zero Configuration Needed**: Works out of the box with sensible defaults; learns your applications' profiles over time.
- **Systemd Integration**: Runs seamlessly as a systemd user service alongside your Hyprland session.

---

## Installation

### Arch Linux (Recommended)

Clone the repository and run the automated installer:

```bash
git clone https://github.com/ctlinker/hyprsmart.git
cd hyprsmart
./install.sh --arch --enable
```

> **Tip**: This builds the native Arch package via `makepkg` and immediately enables the systemd user service.

### Other Distributions / Manual Install

The universal installer also supports system-wide and user-level installations:

```bash
# System-wide installation (/opt/hyprsmart + /usr/bin/hyprsmart)
./install.sh --system --enable

# User-level installation (~/.local/bin) without sudo
./install.sh --user --enable
```

To uninstall at any time:
```bash
./install.sh --uninstall
```

---

## Autostart

### Option A: systemd User Service (Recommended)
If you didn't pass `--enable` during installation, enable and start the service with:

```bash
systemctl --user enable --now hyprsmart.service
```

### Option B: Hyprland Config (`hyprland.conf`)
Alternatively, add this line to `~/.config/hypr/hyprland.conf`:

```ini
exec-once = hyprsmart start
```

---

## Quick Usage

Once installed, use the `hyprsmart` CLI to control the daemon:

```bash
# Check daemon status
hyprsmart status

# Watch live opacity decisions in real-time
hyprsmart what-is-it-doing --watch

# Stop the daemon (automatically restores all windows to 100% opacity)
hyprsmart stop

# Start the daemon in background
hyprsmart start
```

### Basic Settings

Adjust key settings on the fly without restarting:

```bash
# View current settings
hyprsmart settings

# Set minimum opacity floor (e.g. 0.45)
hyprsmart settings floor_opacity 0.45

# Adjust target contrast (default: 6.0)
hyprsmart settings target_contrast 6.0
```

### Protecting Sensitive Apps

Add sensitive window classes to the built-in privacy shield:

```bash
# List shielded applications
hyprsmart blacklist list

# Add an app to the shield
hyprsmart blacklist add myapp
```

---

## Technical Documentation & Development

Looking for the mathematical formulas, architectural diagrams, developer flags, or source code build instructions?

- [**Technical & Developer Guide (`hyprsmart/README.md`)**](hyprsmart/README.md): Internal architecture, pipeline flowchart, optical unblending formulas, development with `uv`, tests, and diagnostics.
- [**HyprSmart Wiki (`docs/wiki/README.md`)**](docs/wiki/README.md): In-depth technical papers on WCAG luminance, Sobel clutter detection, PipeWire video detection, and session journals.

---

## License

Distributed under the [MIT License](LICENSE).
