#!/usr/bin/env bash
# ============================================================================
# uConsole Field Kit — Complete One-Stop Installer
# ============================================================================
# Installs everything on a fresh Rex Debian 12 Bookworm (akrex kernel 6.12.67)
# uConsole CM5 image with a HackerGadgets AIO V2 board.
#
# Run from the repo root on the uConsole:
#     sudo ./install.sh
#
# Installs: aiov2_ctl, AIO companion apps, Meshtastic CLI+daemon, MeshCore,
# MeshDash, iNTERCEPT, WSJT-X, Contact TUI, SDR tools, GPS tools,
# SSH, VNC, power-button daemon, backlight control, mesh mode switcher,
# diagnostics, and the Field Launcher kiosk UI.
# ============================================================================

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

log "================================================================"
log " uConsole Field Kit — Complete Installer"
log " User: $USER_NAME   Arch: $ARCH   Root: $(findmnt -no SOURCE /)"
log "================================================================"
echo

# ----------------------------------------------------------------------------
# Phase 1 — Base system packages
# ----------------------------------------------------------------------------
log "[1/13] Updating system and installing base packages..."

apt-get update
apt-get full-upgrade -y

apt_install \
    ca-certificates curl wget git jq unzip rsync \
    python3 python3-pip python3-venv python3-pyqt6 python3-evdev pipx \
    build-essential pkg-config cmake ninja-build \
    gpiod libgpiod-dev usbutils pciutils \
    rtl-sdr rtl-433 gpsd gpsd-clients \
    minicom picocom screen \
    nmap mtr-tiny iperf3 tcpdump \
    mosquitto-clients \
    nvme-cli smartmontools lm-sensors htop btop iotop powertop \
    network-manager wireguard-tools \
    cloud-guest-utils gdisk acpid \
    openssh-server \
    x11vnc xvfb \
    xfce4 xfce4-terminal \
    chrony \
    wsjtx \
    jq

# Node-RED (from apt if available, else npm)
if apt-cache show node-red >/dev/null 2>&1; then
    apt_install node-red
else
    log "  node-red not in apt — installing via npm"
    apt_install nodejs npm
    npm install -g --unsafe-perm node-red || log "  node-red npm install failed (non-fatal)"
fi

log "  Base packages installed."

# ----------------------------------------------------------------------------
# Phase 2 — aiov2_ctl (GPIO control + boot-rail service)
# ----------------------------------------------------------------------------
log "[2/13] Installing aiov2_ctl..."

if apt-cache show hackergadgets-uconsole-aio-board >/dev/null 2>&1; then
    apt_install hackergadgets-uconsole-aio-board
else
    rm -rf /opt/aiov2_ctl
    git clone --depth 1 https://github.com/hackergadgets/aiov2_ctl.git /opt/aiov2_ctl
    python3 /opt/aiov2_ctl/aiov2_ctl.py --install
fi

# Configure boot-rail preferences from defaults
install -m 0755 "$SCRIPT_DIR/scripts/aio-boot.sh" /usr/local/sbin/uconsole-aio-boot
/usr/local/sbin/uconsole-aio-boot || log "  Boot-rail configuration partially failed (non-fatal)."

log "  aiov2_ctl installed and boot rails configured."

# ----------------------------------------------------------------------------
# Phase 3 — HackerGadgets AIO companion apps
# ----------------------------------------------------------------------------
log "[3/13] Installing HackerGadgets AIO companion apps..."

aiov2_ctl --add-apps || log "  Companion app installation failed (non-fatal). Some apps may need manual install."

# Backlight control (from Rex's repo)
apt_install clockworkpi-backlight || log "  clockworkpi-backlight not available (non-fatal)."

log "  Companion apps installed (sdrpp-brown, meshtastic-mui, tar1090, pygpsclient)."

# ----------------------------------------------------------------------------
# Phase 4 — SSH and VNC
# ----------------------------------------------------------------------------
log "[4/13] Enabling SSH and VNC..."

# SSH
systemctl enable --now ssh

# VNC: x11vnc listening on :0 (shares the physical display)
# Generate a default VNC password if none exists
VNC_PASS_FILE="/etc/x11vnc.pass"
if [[ ! -f "$VNC_PASS_FILE" ]]; then
    x11vnc -storepasswd "$(head -c 16 /dev/urandom | base64 | tr -d '/+=' | head -c 12)" "$VNC_PASS_FILE"
    log "  VNC auto-password generated. Change with: sudo x11vnc -storepasswd <pass> $VNC_PASS_FILE"
fi

cat > /etc/systemd/system/x11vnc.service <<'UNIT'
[Unit]
Description=x11vnc VNC server (shares physical display)
After=graphical.target
Requires=graphical.target

[Service]
Type=simple
ExecStart=/usr/bin/x11vnc -display :0 -rfbauth /etc/x11vnc.pass -rfbport 5900 -shared -forever -bg -o /var/log/x11vnc.log
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical.target
UNIT

systemctl daemon-reload
systemctl enable x11vnc.service

log "  SSH enabled (port 22). VNC enabled (port 5900, shares physical display)."

# ----------------------------------------------------------------------------
# Phase 5 — Meshtastic CLI, daemon, and Contact TUI
# ----------------------------------------------------------------------------
log "[5/13] Installing Meshtastic CLI, meshtasticd, Contact TUI, and MeshCore TUI..."

sudo -u "$USER_NAME" env HOME="$USER_HOME" pipx ensurepath || true
sudo -u "$USER_NAME" env HOME="$USER_HOME" pipx install --force meshtastic
sudo -u "$USER_NAME" env HOME="$USER_HOME" pipx install contact
# MeshCore TUI (guax/tui-meshcore) — terminal chat client for MeshCore
sudo -u "$USER_NAME" env HOME="$USER_HOME" pipx install tui-meshcore || log "  tui-meshcore not on PyPI — try: pipx install git+https://github.com/guax/tui-meshcore.git"

if apt-cache show meshtasticd >/dev/null 2>&1; then
    apt_install meshtasticd
    systemctl disable --now meshtasticd || true
else
    log "  meshtasticd not in apt repos — CLI only."
fi

log "  Meshtastic CLI, meshtasticd, Contact TUI, and MeshCore TUI installed."

# ----------------------------------------------------------------------------
# Phase 6 — MeshCore
# ----------------------------------------------------------------------------
log "[6/13] Installing MeshCore uConsole integration..."

rm -rf /opt/meshcore-uconsole
git clone --depth 1 --branch "$MESHCORE_BRANCH" "$MESHCORE_REPOSITORY" /opt/meshcore-uconsole
if [[ -x /opt/meshcore-uconsole/install.sh ]]; then
    /opt/meshcore-uconsole/install.sh
elif [[ -x /opt/meshcore-uconsole/setup.sh ]]; then
    /opt/meshcore-uconsole/setup.sh
elif [[ -f /opt/meshcore-uconsole/README.md ]]; then
    log "  MeshCore cloned but no unattended installer found. Read /opt/meshcore-uconsole/README.md"
else
    log "  MeshCore repository structure not recognised."
fi

log "  MeshCore installed."

# ----------------------------------------------------------------------------
# Phase 7 — MeshDash
# ----------------------------------------------------------------------------
log "[7/13] Installing MeshDash $MESHDASH_VERSION..."

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
    log "  MeshDash installed and service enabled."
else
    log "  MeshDash archive did not contain meshtastic_dashboard.py — service not created."
fi

# ----------------------------------------------------------------------------
# Phase 8 — iNTERCEPT (SIGINT platform — Full install)
# ----------------------------------------------------------------------------
log "[8/13] Installing iNTERCEPT (Full SIGINT)..."

# Extra deps noted from the forum thread
apt_install python3-skyfield || log "  python3-skyfield not available (satellite features may be limited)."

rm -rf /opt/intercept
git clone --depth 1 https://github.com/smittix/intercept.git /opt/intercept
cd /opt/intercept
# Interactive setup — choose "Full SIGINT" profile when prompted.
# This installs all decoders: pager, 433MHz, ADS-B, ACARS, VDL2, AIS,
# APRS, weather satellites, SSTV, WeFax, WiFi, Bluetooth, GPS, and more.
./setup.sh || log "  iNTERCEPT setup.sh failed. Manual setup: cd /opt/intercept && ./setup.sh"
cd "$SCRIPT_DIR"
chown -R "$USER_NAME:$USER_NAME" /opt/intercept

log "  iNTERCEPT installed (Full SIGINT, web UI at http://localhost:5050)."

# ----------------------------------------------------------------------------
# Phase 9 — rpitx-ui (RF transmitter)
# ----------------------------------------------------------------------------
log "[9/13] Installing rpitx-ui (RF transmitter)..."

rm -rf /opt/rpitx-ui
git clone --depth 1 https://github.com/IgrikXD/rpitx-ui.git /opt/rpitx-ui
cd /opt/rpitx-ui
./install.sh || log "  rpitx-ui install.sh failed. Manual build: cd /opt/rpitx-ui && mkdir build && cd build && cmake .. && make -j\$(nproc) && sudo make install"
cd "$SCRIPT_DIR"

log "  rpitx-ui installed (run with: rpitx-ui). FM, SSB, CW, SSTV, FT8, RDS transmit via AIO RF output."

# ----------------------------------------------------------------------------
# Phase 10 — Power button daemon + display handler
# ----------------------------------------------------------------------------
log "[10/13] Installing power button daemon and display handler..."

install -m 0755 "$SCRIPT_DIR/scripts/uconsole-display" /usr/local/bin/uconsole-display
install -m 0755 "$SCRIPT_DIR/scripts/power-button-daemon.py" /usr/local/sbin/uconsole-power-button-daemon
install -m 0644 "$SCRIPT_DIR/systemd/uconsole-power-button.service" /etc/systemd/system/uconsole-power-button.service
mkdir -p /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/90-uconsole-power-button.conf <<'EOF'
[Login]
HandlePowerKey=ignore
HandlePowerKeyLongPress=poweroff
EOF

log "  Power button daemon installed (short press = display toggle, long press = poweroff)."

# ----------------------------------------------------------------------------
# Phase 11 — Mesh mode switcher, diagnostics, and config
# ----------------------------------------------------------------------------
log "[11/13] Installing mesh switcher, diagnostics, and field launcher..."

install -m 0755 "$SCRIPT_DIR/scripts/uconsole-radio" /usr/local/bin/uconsole-radio
install -m 0755 "$SCRIPT_DIR/scripts/uconsole-doctor" /usr/local/bin/uconsole-doctor
install -m 0755 "$SCRIPT_DIR/scripts/field-launcher.py" /usr/local/bin/field-launcher

# Write config file
cat > /etc/default/uconsole-field-kit <<EOF
AIO_GPS_ON_BOOT=$AIO_GPS_ON_BOOT
AIO_SDR_ON_BOOT=$AIO_SDR_ON_BOOT
AIO_USB_ON_BOOT=$AIO_USB_ON_BOOT
AIO_LORA_ON_BOOT=$AIO_LORA_ON_BOOT
DEFAULT_MESH_MODE=$DEFAULT_MESH_MODE
EOF

# Field launcher autostart
mkdir -p "$USER_HOME/.config/autostart"
cp "$SCRIPT_DIR/systemd/field-launcher.desktop" "$USER_HOME/.config/autostart/"
chown -R "$USER_NAME:$USER_NAME" "$USER_HOME/.config/autostart"

log "  Mesh switcher, diagnostics, and field launcher installed."
log "  Field launcher will auto-start on login."

# ----------------------------------------------------------------------------
# Phase 12 — GPS NTP (chrony + gpsd), RTC sync, systemd enable
# ----------------------------------------------------------------------------
log "[12/13] Configuring GPS NTP, RTC, and enabling services..."

# Configure gpsd for the AIO GPS module
cat > /etc/default/gpsd <<'EOF'
# Default settings for gpsd
START_DAEMON=true
GPSD_OPTIONS="-n"
DEVICES="/dev/ttyAMA0"
USBAUTO=false
EOF

# Configure chrony to use GPS as a time source (Stratum 1)
if [[ -f /etc/chrony/chrony.conf ]]; then
    if ! grep -q "refclock SHM 0" /etc/chrony/chrony.conf; then
        cat >> /etc/chrony/chrony.conf <<'EOF'

# GPS PPS time source (via gpsd shared memory)
refclock SHM 0 offset 0.5 delay 0.2 refid GPS
# Allow clients on local network to query time
allow 192.168.0.0/16
allow 10.0.0.0/8
EOF
    fi
fi

systemctl enable gpsd
systemctl restart gpsd || true
systemctl enable chrony || true
systemctl restart chrony || true

# RTC sync
aiov2_ctl --sync-rtc || log "  RTC sync failed (non-fatal — may need NTP first)."

# Enable services
systemctl daemon-reload
systemctl enable uconsole-power-button.service
systemctl restart systemd-logind || true

log "  GPS NTP (chrony + gpsd) configured. RTC synced."

# ----------------------------------------------------------------------------
# Phase 13 — Final summary and diagnostics
# ----------------------------------------------------------------------------
log "[13/13] Finalising..."

# Set default mesh mode
case "$DEFAULT_MESH_MODE" in
    meshcore|meshtastic|off)
        /usr/local/bin/uconsole-radio "$DEFAULT_MESH_MODE" || true
        ;;
    *)
        log "  Invalid DEFAULT_MESH_MODE=$DEFAULT_MESH_MODE — leaving mesh stopped."
        ;;
esac

echo
log "================================================================"
log " Installation complete!"
log "================================================================"
echo
echo " SSH:   ssh $USER_NAME@<uconsole-ip>"
echo " VNC:   <uconsole-ip>:5900  (password in /etc/x11vnc.pass)"
echo " MeshDash:    http://localhost:8000/setup"
echo " iNTERCEPT:   http://localhost:5050  (start with: cd /opt/intercept && sudo ./start.sh)"
echo " rpitx-ui:    rpitx-ui  (FM/SSB/CW/SSTV/FT8 transmit via AIO RF output)"
echo " Field Launcher: auto-starts on login (run 'field-launcher' to restart)"
echo
echo " Commands:"
echo "   uconsole-doctor        — system diagnostics"
echo "   uconsole-radio status   — mesh status"
echo "   aiov2_ctl --status       — AIO board + battery status"
echo "   contact --port /dev/ttyUSB0  — Meshtastic TUI"
echo "   tui-meshcore                — MeshCore TUI"
echo "   rpitx-ui                    — RF transmitter UI"
echo "   field-launcher              — restart the launcher UI"
echo
echo " VNC password:  $(cat /etc/x11vnc.pass 2>/dev/null | head -c 12 || echo 'see /etc/x11vnc.pass')"
echo
uconsole-doctor || true
echo
log "Reboot with: sudo reboot"
log "After reboot the Field Launcher will appear automatically."
