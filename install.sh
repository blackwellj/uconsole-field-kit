#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/common.sh"
need_root

CONFIG_FILE="$SCRIPT_DIR/config/defaults.env"
[[ -f "$CONFIG_FILE" ]] || die "Missing $CONFIG_FILE"
# shellcheck disable=SC1090
source "$CONFIG_FILE"

USER_NAME="$(real_user)"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
ARCH="$(dpkg --print-architecture)"

log "Installing uConsole Field Kit for user $USER_NAME on $ARCH."
log "Root filesystem: $(findmnt -no SOURCE /)"

apt-get update
apt-get full-upgrade -y

apt_install \
    ca-certificates curl wget git jq unzip rsync \
    python3 python3-pip python3-venv python3-pyqt6 python3-evdev pipx \
    build-essential pkg-config cmake ninja-build \
    gpiod libgpiod-dev usbutils pciutils \
    rtl-sdr rtl-433 gpsd gpsd-clients \
    minicom picocom screen \
    nmap mtr-tiny iperf3 tcpdump wireshark-common \
    mosquitto-clients \
    nvme-cli smartmontools lm-sensors htop btop iotop powertop \
    network-manager wireguard-tools \
    cloud-guest-utils gdisk acpid

if apt-cache show node-red >/dev/null 2>&1; then
    apt_install node-red
else
    log "node-red is not in the configured APT repositories. Installing through npm."
    apt_install nodejs npm
    npm install -g --unsafe-perm node-red
fi

if apt-cache show sdrpp >/dev/null 2>&1; then
    apt_install sdrpp
else
    log "SDR++ is not available from the configured repositories. Rex's repository may need enabling."
fi

log "Installing HackerGadgets AIO support."
if apt-cache show hackergadgets-uconsole-aio-board >/dev/null 2>&1; then
    apt_install hackergadgets-uconsole-aio-board
else
    rm -rf /opt/aiov2_ctl
    git clone --depth 1 https://github.com/hackergadgets/aiov2_ctl.git /opt/aiov2_ctl
    python3 /opt/aiov2_ctl/aiov2_ctl.py --install
fi

# Configure aiov2_ctl's built-in boot-rail preferences from our defaults,
# then let the upstream aiov2-rails-boot.service own GPIO at boot.
install -m 0755 "$SCRIPT_DIR/scripts/aio-boot.sh" /usr/local/sbin/uconsole-aio-boot
/usr/local/sbin/uconsole-aio-boot

log "Installing HackerGadgets AIO companion apps (SDR++, Meshtastic GUI, GPS, tar1090)."
aiov2_ctl --add-apps || log "Companion app installation failed or not available."

log "Installing display power button handler."
install -m 0755 "$SCRIPT_DIR/scripts/uconsole-display" /usr/local/bin/uconsole-display
install -m 0755 "$SCRIPT_DIR/scripts/power-button-daemon.py" /usr/local/sbin/uconsole-power-button-daemon
install -m 0644 "$SCRIPT_DIR/systemd/uconsole-power-button.service" /etc/systemd/system/uconsole-power-button.service
mkdir -p /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/90-uconsole-power-button.conf <<'EOF'
[Login]
HandlePowerKey=ignore
HandlePowerKeyLongPress=poweroff
EOF

log "Installing Meshtastic CLI."
sudo -u "$USER_NAME" env HOME="$USER_HOME" pipx ensurepath || true
sudo -u "$USER_NAME" env HOME="$USER_HOME" pipx install --force meshtastic

log "Attempting to install meshtasticd."
if apt-cache show meshtasticd >/dev/null 2>&1; then
    apt_install meshtasticd
    systemctl disable --now meshtasticd || true
else
    log "meshtasticd is not available from the current APT sources. CLI support is installed; native daemon installation was skipped."
fi

log "Installing MeshCore uConsole integration."
rm -rf /opt/meshcore-uconsole
git clone --depth 1 --branch "$MESHCORE_BRANCH" "$MESHCORE_REPOSITORY" /opt/meshcore-uconsole
if [[ -x /opt/meshcore-uconsole/install.sh ]]; then
    /opt/meshcore-uconsole/install.sh
elif [[ -x /opt/meshcore-uconsole/setup.sh ]]; then
    /opt/meshcore-uconsole/setup.sh
elif [[ -f /opt/meshcore-uconsole/README.md ]]; then
    log "MeshCore repository cloned, but no recognised unattended installer was found."
    log "Read /opt/meshcore-uconsole/README.md before starting MeshCore."
else
    log "MeshCore repository structure was not recognised."
fi

log "Installing MeshDash $MESHDASH_VERSION."
rm -rf /opt/meshdash
mkdir -p /opt/meshdash
wget -O /tmp/mesh-dash.zip "$MESHDASH_ZIP_URL"
unzip -q /tmp/mesh-dash.zip -d /opt/meshdash
rm -f /tmp/mesh-dash.zip

MESHDASH_APP="$(find /opt/meshdash -type f -name meshtastic_dashboard.py -printf '%h\n' | head -n1)"
if [[ -n "$MESHDASH_APP" ]]; then
    python3 -m venv /opt/meshdash/venv
    /opt/meshdash/venv/bin/pip install --upgrade pip wheel
    if [[ -f "$MESHDASH_APP/requirements.txt" ]]; then
        /opt/meshdash/venv/bin/pip install --no-cache-dir -r "$MESHDASH_APP/requirements.txt"
    fi
    chown -R "$USER_NAME:$USER_NAME" /opt/meshdash
    sed \
        -e "s|@@USER@@|$USER_NAME|g" \
        -e "s|@@WORKDIR@@|$MESHDASH_APP|g" \
        "$SCRIPT_DIR/systemd/mesh-dash.service.in" \
        > /etc/systemd/system/mesh-dash.service
    systemctl enable mesh-dash.service
else
    log "MeshDash archive did not contain meshtastic_dashboard.py. MeshDash service was not created."
fi

install -m 0755 "$SCRIPT_DIR/scripts/uconsole-radio" /usr/local/bin/uconsole-radio
install -m 0755 "$SCRIPT_DIR/scripts/uconsole-doctor" /usr/local/bin/uconsole-doctor

cat > /etc/default/uconsole-field-kit <<EOF
AIO_GPS_ON_BOOT=$AIO_GPS_ON_BOOT
AIO_SDR_ON_BOOT=$AIO_SDR_ON_BOOT
AIO_USB_ON_BOOT=$AIO_USB_ON_BOOT
AIO_LORA_ON_BOOT=$AIO_LORA_ON_BOOT
DEFAULT_MESH_MODE=$DEFAULT_MESH_MODE
EOF

systemctl daemon-reload
systemctl enable uconsole-power-button.service
systemctl restart systemd-logind || true

log "Syncing system time to hardware RTC."
aiov2_ctl --sync-rtc || true

case "$DEFAULT_MESH_MODE" in
    meshcore|meshtastic|off)
        /usr/local/bin/uconsole-radio "$DEFAULT_MESH_MODE" || true
        ;;
    *)
        log "Invalid DEFAULT_MESH_MODE=$DEFAULT_MESH_MODE. Leaving mesh services stopped."
        ;;
esac

log "Installation finished."
echo
uconsole-doctor || true
echo
echo "Reboot with: sudo reboot"
echo "After reboot, open MeshDash at http://localhost:8000/setup"
