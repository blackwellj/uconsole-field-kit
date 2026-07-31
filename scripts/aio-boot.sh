#!/usr/bin/env bash
set -Eeuo pipefail
[[ -f /etc/default/uconsole-field-kit ]] && source /etc/default/uconsole-field-kit

set_module() {
    local module="$1"
    local desired="$2"
    if [[ "$desired" == 1 ]]; then
        aiov2_ctl "$module" on
    else
        aiov2_ctl "$module" off
    fi
}

command -v aiov2_ctl >/dev/null 2>&1 || exit 1
set_module GPS "${AIO_GPS_ON_BOOT:-1}"
set_module SDR "${AIO_SDR_ON_BOOT:-1}"
set_module USB "${AIO_USB_ON_BOOT:-1}"
set_module LORA "${AIO_LORA_ON_BOOT:-1}"
