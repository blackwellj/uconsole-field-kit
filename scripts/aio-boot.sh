#!/usr/bin/env bash
set -Eeuo pipefail

# Apply AIO v2 module power states for the current boot.
#
# aiov2_ctl --install already created and enabled aiov2-rails-boot.service,
# which reads persisted per-rail boot preferences from
# /usr/local/share/aiov2_ctl/config.json.  This script configures those
# preferences from /etc/default/uconsole-field-kit so that the upstream
# service (not a duplicate one) applies them at every boot.

CONFIG_FILE="/etc/default/uconsole-field-kit"
[[ -f "$CONFIG_FILE" ]] && source "$CONFIG_FILE"

command -v aiov2_ctl >/dev/null 2>&1 || {
    echo "aiov2_ctl not installed — cannot set boot rails." >&2
    exit 1
}

set_boot_rail() {
    local module="$1"
    local desired="${2:-0}"
    if [[ "$desired" == 1 ]]; then
        aiov2_ctl --boot-rail "$module" on >/dev/null 2>&1 || true
    else
        aiov2_ctl --boot-rail "$module" off >/dev/null 2>&1 || true
    fi
}

set_boot_rail GPS  "${AIO_GPS_ON_BOOT:-1}"
set_boot_rail SDR  "${AIO_SDR_ON_BOOT:-1}"
set_boot_rail USB  "${AIO_USB_ON_BOOT:-1}"
set_boot_rail LORA "${AIO_LORA_ON_BOOT:-1}"

# Apply the rails now so the current boot reflects them immediately.
aiov2_ctl --apply-boot-rails >/dev/null 2>&1 || true
