#!/usr/bin/env bash
# ==============================================================================
# HyprSmart - Git Online Installer
# Fetches the latest release tag from GitHub, clones it, and runs install.sh
# Usage: curl -fSsL https://raw.githubusercontent.com/ctlinker/hyprsmart/main/install-git.sh | bash
# ==============================================================================

set -euo pipefail

# Visual formatting
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

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

# Verify git is available
command -v git >/dev/null 2>&1 || die "Git is required to install HyprSmart. Please install 'git' first."

REPO_URL="${HYPRSMART_REPO:-https://github.com/ctlinker/hyprsmart.git}"
TARGET_REF="${HYPRSMART_REF:-}"

echo -e "${BOLD}==> HyprSmart Online Git Installer${NC}"

# Find the latest tag if no specific ref was provided
if [ -z "${TARGET_REF}" ]; then
    info "Querying latest release tag from ${REPO_URL}..."
    LATEST_TAG=$(git ls-remote --tags --refs "${REPO_URL}" 2>/dev/null \
        | awk '{print $2}' \
        | sed 's|^refs/tags/||' \
        | sort -V \
        | tail -n 1 || true)

    if [ -n "${LATEST_TAG}" ]; then
        TARGET_REF="${LATEST_TAG}"
        info "Found latest release tag: ${BOLD}${TARGET_REF}${NC}"
    else
        TARGET_REF="main"
        warn "No release tags found. Falling back to branch: ${BOLD}${TARGET_REF}${NC}"
    fi
else
    info "Using requested target ref: ${BOLD}${TARGET_REF}${NC}"
fi

# Create a temporary directory for cloning
TMP_DIR=$(mktemp -d -t hyprsmart-git-install.XXXXXXXXXX)
trap 'rm -rf "${TMP_DIR}"' EXIT

info "Cloning ${TARGET_REF} into temporary directory..."
if ! git clone --depth 1 --branch "${TARGET_REF}" "${REPO_URL}" "${TMP_DIR}/hyprsmart" 2>/dev/null; then
    # Fallback if shallow clone with tag requires full clone on some git versions
    git clone "${REPO_URL}" "${TMP_DIR}/hyprsmart"
    (cd "${TMP_DIR}/hyprsmart" && git checkout "${TARGET_REF}")
fi

cd "${TMP_DIR}/hyprsmart"

if [ ! -f "./install.sh" ]; then
    warn "install.sh was not found in release ref '${TARGET_REF}' (introduced in v0.8.6+)."
    warn "Fetching development branch 'dev' to obtain install.sh..."
    (git fetch --depth 1 origin dev:dev 2>/dev/null && git checkout dev 2>/dev/null) || \
    (git fetch --depth 1 origin main:main 2>/dev/null && git checkout main 2>/dev/null) || true
fi

if [ ! -f "./install.sh" ]; then
    die "install.sh not found in the cloned repository (${TARGET_REF})."
fi

chmod +x ./install.sh

# If no arguments were supplied, enable service by default
INSTALL_ARGS=("$@")
if [ ${#INSTALL_ARGS[@]} -eq 0 ]; then
    INSTALL_ARGS=("--enable")
fi

info "Launching installer..."
echo ""
if [ -e /dev/tty ]; then
    ./install.sh "${INSTALL_ARGS[@]}" < /dev/tty
else
    ./install.sh "${INSTALL_ARGS[@]}"
fi
