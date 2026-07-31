#!/usr/bin/env bash
set -Eeuo pipefail

LOG_FILE="${LOG_FILE:-/var/log/uconsole-field-kit.log}"

log() {
    printf '%s %s\n' "$(date --iso-8601=seconds)" "$*" | tee -a "$LOG_FILE"
}

die() {
    log "ERROR: $*"
    exit 1
}

need_root() {
    [[ "${EUID}" -eq 0 ]] || die "Run this command with sudo."
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

retry() {
    local attempts="$1"
    shift
    local count=1
    until "$@"; do
        if (( count >= attempts )); then
            return 1
        fi
        log "Command failed. Retrying ${count}/${attempts}: $*"
        sleep 3
        ((count++))
    done
}

apt_install() {
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
}

real_user() {
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != root ]]; then
        printf '%s\n' "$SUDO_USER"
    else
        local user
        user="$(getent passwd 1000 | cut -d: -f1 || true)"
        [[ -n "$user" ]] || user="$(logname 2>/dev/null || true)"
        [[ -n "$user" ]] || user="root"
        printf '%s\n' "$user"
    fi
}
