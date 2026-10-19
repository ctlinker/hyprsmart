#!/usr/bin/env bash
# ==============================================================================
# HyprSmart - Installer Script
# Adaptive window transparency daemon for Hyprland
# ==============================================================================

set -euo pipefail

# Visual formatting
BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION=$(grep -m1 'version = ' "${SCRIPT_DIR}/hyprsmart/pyproject.toml" | cut -d'"' -f2 || echo "0.8.5")

info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

ok() {
    echo -e "${GREEN}[OK]${NC} $*"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

die() {
    error "$*"
    exit 1
}

# Print header
print_banner() {
    echo -e "${CYAN}${BOLD}"
    echo "  _   _                  ____                       _   "
    echo " | | | |_   _ _ __  _ __/ ___| _ __ ___   __ _ _ __| |_ "
    echo " | |_| | | | | '_ \| '__\___ \| '_ ' _ \ / _' | '__| __|"
    echo " |  _  | |_| | |_) | |   ___) | | | | | | (_| | |  | |_ "
    echo " |_| |_|\__, | .__/|_|  |____/|_| |_| |_|\__,_|_|   \__|"
    echo "        |___/|_|                                         "
    echo -e "${NC}"
    echo -e "${BOLD}HyprSmart Installer v${VERSION}${NC} — Adaptive Transparency for Hyprland"
    echo "-------------------------------------------------------------"
}

show_help() {
    print_banner
    echo -e "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -a, --arch         Build and install native Arch Linux package (makepkg -si)"
    echo "  -s, --system       Build and install system-wide (/opt/hyprsmart, /usr/bin/)"
    echo "  -u, --user         Install locally for current user (~/.local/share/hyprsmart, ~/.local/bin/)"
    echo "      --enable       Automatically enable and start systemd user service"
    echo "      --uninstall    Uninstall HyprSmart (removes binaries and systemd units)"
    echo "  -h, --help         Show this help message"
    echo ""
    echo "Examples:"
    echo "  ./install.sh --arch --enable     # Build & install Arch package + start systemd service"
    echo "  ./install.sh --user --enable     # Install in ~/.local without root privileges"
    echo "  ./install.sh --uninstall         # Remove HyprSmart completely"
    exit 0
}

# Check runtime and build dependencies
check_dependencies() {
    local missing_build=()
    local missing_runtime=()

    command -v python3 >/dev/null 2>&1 || missing_build+=("python3")
    command -v uv >/dev/null 2>&1 || missing_build+=("uv")

    command -v hyprctl >/dev/null 2>&1 || missing_runtime+=("hyprctl (from hyprland)")
    command -v grim >/dev/null 2>&1 || missing_runtime+=("grim")

    if [ ${#missing_build[@]} -gt 0 ]; then
        die "Missing required build tools: ${missing_build[*]}\nPlease install them before proceeding."
    fi

    if [ ${#missing_runtime[@]} -gt 0 ]; then
        warn "Missing optional/runtime tools: ${missing_runtime[*]}"
        warn "HyprSmart requires Hyprland and grim to adjust opacity at runtime."
    fi
}

# Build binary using PyInstaller & uv
build_binary() {
    info "Building HyprSmart standalone binary with uv & PyInstaller..."
    cd "${SCRIPT_DIR}/hyprsmart"
    uv venv --clear
    uv sync
    uv run python -m PyInstaller \
        --clean \
        --noconfirm \
        --onedir \
        --name hyprsmart \
        --collect-all numpy \
        --collect-all PIL \
        --collect-all yaml \
        src/hyprsmart/__main__.py
    cd "${SCRIPT_DIR}"
    ok "Build completed successfully: hyprsmart/dist/hyprsmart"
}

# Arch Linux Package installation
install_arch() {
    info "Preparing Arch Linux package (PKGBUILD)..."
    command -v makepkg >/dev/null 2>&1 || die "makepkg not found! Are you running Arch Linux?"

    local arch_dir="${SCRIPT_DIR}/packaging/arch"
    local tarball="${arch_dir}/hyprsmart-${VERSION}.tar.gz"

    # Create local source tarball for makepkg from git HEAD or directory
    info "Creating source tarball for makepkg: ${tarball}"
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        git archive --format=tar.gz --prefix="hyprsmart-${VERSION}/" HEAD -o "${tarball}"
    else
        tar --exclude='./.git' --exclude='./packaging/arch/pkg' --exclude='./packaging/arch/src' \
            --transform="s,^\.,hyprsmart-${VERSION}," -czf "${tarball}" .
    fi

    info "Building and installing Arch package with makepkg..."
    cd "${arch_dir}"
    makepkg -sfi --noconfirm
    cd "${SCRIPT_DIR}"

    # Clean up local tarball created for makepkg
    rm -f "${tarball}"
    ok "HyprSmart Arch Linux package installed successfully."
}

# System-wide installation (/opt + /usr/bin + /usr/lib/systemd/user)
install_system() {
    build_binary

    info "Installing to /opt/hyprsmart and /usr/bin/hyprsmart (sudo required)..."
    sudo install -dm755 /opt/hyprsmart
    sudo cp -a "${SCRIPT_DIR}/hyprsmart/dist/hyprsmart/." /opt/hyprsmart/
    sudo install -dm755 /usr/bin
    sudo ln -sf /opt/hyprsmart/hyprsmart /usr/bin/hyprsmart

    info "Installing systemd user service to /usr/lib/systemd/user/hyprsmart.service..."
    sudo install -Dm644 "${SCRIPT_DIR}/packaging/arch/hyprsmart.service" /usr/lib/systemd/user/hyprsmart.service

    ok "System-wide installation completed."
}

# User-level installation (~/.local/share + ~/.local/bin + ~/.config/systemd/user)
install_user() {
    build_binary

    local user_opt="${HOME}/.local/share/hyprsmart"
    local user_bin="${HOME}/.local/bin"
    local user_service_dir="${HOME}/.config/systemd/user"

    info "Installing to ${user_opt} and linking into ${user_bin}..."
    mkdir -p "${user_opt}" "${user_bin}"
    cp -a "${SCRIPT_DIR}/hyprsmart/dist/hyprsmart/." "${user_opt}/"
    ln -sf "${user_opt}/hyprsmart" "${user_bin}/hyprsmart"

    info "Installing user systemd service into ${user_service_dir}/hyprsmart.service..."
    mkdir -p "${user_service_dir}"
    sed "s|/usr/bin/hyprsmart|%h/.local/bin/hyprsmart|g" \
        "${SCRIPT_DIR}/packaging/arch/hyprsmart.service" > "${user_service_dir}/hyprsmart.service"

    ok "User-level installation completed."
    echo -e "${YELLOW}[NOTE]${NC} Ensure ${BOLD}${user_bin}${NC} is in your PATH."
}

# Enable and start systemd user service
enable_service() {
    info "Configuring and starting systemd user service..."
    systemctl --user daemon-reload
    systemctl --user enable --now hyprsmart.service
    ok "HyprSmart systemd user service enabled and started!"
    echo ""
    systemctl --user status hyprsmart.service --no-pager || true
}

# Uninstall HyprSmart
uninstall_hyprsmart() {
    info "Stopping and disabling HyprSmart service..."
    systemctl --user stop hyprsmart.service 2>/dev/null || true
    systemctl --user disable hyprsmart.service 2>/dev/null || true

    # If installed via pacman
    if command -v pacman >/dev/null 2>&1 && pacman -Q hyprsmart >/dev/null 2>&1; then
        info "Removing pacman package hyprsmart..."
        sudo pacman -R --noconfirm hyprsmart
    else
        info "Cleaning system files..."
        sudo rm -rf /opt/hyprsmart /usr/bin/hyprsmart /usr/lib/systemd/user/hyprsmart.service 2>/dev/null || true
    fi

    info "Cleaning user files..."
    rm -rf "${HOME}/.local/share/hyprsmart" \
           "${HOME}/.local/bin/hyprsmart" \
           "${HOME}/.config/systemd/user/hyprsmart.service" \
           "${HOME}/.config/systemd/user/graphical-session.target.wants/hyprsmart.service" \
           "${HOME}/.config/systemd/user/multi-user.target.wants/hyprsmart.service" 2>/dev/null || true

    systemctl --user daemon-reload
    ok "HyprSmart has been completely uninstalled."
    exit 0
}

# Main routing
main() {
    local mode=""
    local do_enable=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -a|--arch)
                mode="arch"
                shift
                ;;
            -s|--system)
                mode="system"
                shift
                ;;
            -u|--user)
                mode="user"
                shift
                ;;
            --enable)
                do_enable=true
                shift
                ;;
            --uninstall)
                uninstall_hyprsmart
                ;;
            -h|--help)
                show_help
                ;;
            *)
                error "Unknown option: $1"
                show_help
                ;;
        esac
    done

    print_banner
    check_dependencies

    # Auto-detect mode if not explicitly supplied
    if [ -z "${mode}" ]; then
        if [ -f /etc/arch-release ] && command -v makepkg >/dev/null 2>&1; then
            info "Arch Linux detected! Using Arch packaging mode (makepkg)."
            mode="arch"
        elif [ "$(id -u)" -eq 0 ] || command -v sudo >/dev/null 2>&1; then
            info "Defaulting to system-wide installation."
            mode="system"
        else
            info "Defaulting to user-level installation."
            mode="user"
        fi
    fi

    case "${mode}" in
        arch)
            install_arch
            ;;
        system)
            install_system
            ;;
        user)
            install_user
            ;;
    esac

    # Always reload systemd user daemon after installation
    systemctl --user daemon-reload 2>/dev/null || true

    if [ "${do_enable}" = true ]; then
        enable_service
    else
        echo ""
        echo -e "${BOLD}Next Steps:${NC}"
        echo "1. To start HyprSmart automatically via systemd (recommended):"
        echo -e "   ${CYAN}systemctl --user enable --now hyprsmart.service${NC}"
        echo ""
        echo "2. OR launch it directly inside hyprland.conf:"
        echo -e "   ${CYAN}exec-once = hyprsmart start${NC}"
        echo ""
        echo "3. Check running status at any time with:"
        echo -e "   ${CYAN}hyprsmart status${NC}"
    fi

    ok "Installation process completed!"
}

main "$@"
