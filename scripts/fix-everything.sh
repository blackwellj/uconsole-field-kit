#!/usr/bin/env bash
# uConsole Field Kit — diagnose and fix script
# Run: sudo ./fix-everything.sh
set -Eeuo pipefail

echo "================================================================"
echo " uConsole Diagnose & Fix"
echo "================================================================"
echo

# ---- System info ----
echo "=== SYSTEM ==="
uname -a
cat /proc/device-tree/model 2>/dev/null | tr -d '\0'; echo
echo "Root: $(findmnt -no SOURCE /)"
echo "Uptime: $(uptime -p)"
echo "Memory: $(free -h | awk '/^Mem:/ {print $2 " total, " $7 " free"}')"
echo "Temperature: $(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null | awk '{printf "%.1f°C\n", $1/1000}')"
echo "Swap: $(swapon --show 2>/dev/null | tail -n+2 | awk '{print $1, $3}')"
echo

# ---- Boot order ----
echo "=== EEPROM ==="
if command -v rpi-eeprom-config >/dev/null 2>&1; then
    rpi-eeprom-config 2>/dev/null | grep -E 'BOOT_ORDER|POWER_OFF' || echo "Cannot read EEPROM"
else
    echo "rpi-eeprom-config not available"
fi
echo

# ---- Services ----
echo "=== SERVICES ==="
for svc in ssh x11vnc uconsole-power-button uconsole-power-watchdog \
           mesh-dash gpsd chrony aiov2-rails-boot display-manager lightdm; do
    state=$(systemctl is-active "$svc" 2>/dev/null || echo "n/a")
    enabled=$(systemctl is-enabled "$svc" 2>/dev/null || echo "n/a")
    printf "%-30s active=%-10s enabled=%-10s\n" "$svc" "$state" "$enabled"
done
echo

# ---- Display / backlight ----
echo "=== DISPLAY ==="
echo "Backlight devices:"
ls /sys/class/backlight/ 2>/dev/null || echo "  none"
for bl in /sys/class/backlight/*; do
    [[ -d "$bl" ]] || continue
    cur=$(cat "$bl/brightness" 2>/dev/null)
    max=$(cat "$bl/max_brightness" 2>/dev/null)
    echo "  $(basename "$bl"): $cur/$max"
done
echo "Display manager: $(systemctl is-active display-manager 2>/dev/null || echo 'n/a')"
echo

# ---- AIO board ----
echo "=== AIO V2 ==="
if command -v aiov2_ctl >/dev/null 2>&1; then
    aiov2_ctl 2>/dev/null || echo "aiov2_ctl failed"
    echo
    aiov2_ctl --status 2>/dev/null | head -8 || echo "aiov2_ctl --status failed"
else
    echo "aiov2_ctl not installed"
fi
echo

# ---- Mesh ----
echo "=== MESH ==="
for svc in meshtasticd meshcore meshcore-uconsole meshcore-gui; do
    state=$(systemctl is-active "$svc" 2>/dev/null || echo "n/a")
    [[ "$state" != "n/a" ]] && printf "%-25s %s\n" "$svc" "$state"
done
echo

# ---- Network ----
echo "=== NETWORK ==="
echo "WiFi: $(iwgetid -r 2>/dev/null || echo 'not connected')"
echo "IP: $(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1)"
echo

# ---- Installed software ----
echo "=== SOFTWARE ==="
for cmd in aiov2_ctl meshtastic contact sdrpp-brown sdrpp wsjtx pygpsclient \
           field-launcher uconsole-radio uconsole-doctor uconsole-display; do
    if command -v "$cmd" >/dev/null 2>&1; then
        echo "  [OK] $cmd"
    else
        echo "  [MISSING] $cmd"
    fi
done
echo

echo "================================================================"
echo " Running fixes..."
echo "================================================================"
echo

# ---- Fix 1: Force backlight on ----
echo "[1] Forcing backlight on..."
for bl in /sys/class/backlight/*; do
    [[ -d "$bl" ]] || continue
    max=$(cat "$bl/max_brightness" 2>/dev/null || echo "255")
    echo $max > "$bl/brightness" 2>/dev/null || true
    echo "  Set $(basename $bl) to $max"
done
echo

# ---- Fix 2: Restart display manager ----
echo "[2] Restarting display manager..."
systemctl restart display-manager 2>/dev/null || systemctl restart lightdm 2>/dev/null || echo "  No display manager found"
echo

# ---- Fix 3: Enable and start critical services ----
echo "[3] Enabling services..."
systemctl enable --now ssh 2>/dev/null && echo "  SSH enabled" || true
systemctl enable --now x11vnc 2>/dev/null && echo "  VNC enabled" || true
systemctl enable --now gpsd 2>/dev/null && echo "  GPSd enabled" || true
systemctl enable --now chrony 2>/dev/null && echo "  Chrony enabled" || true
echo

# ---- Fix 4: Install/update field launcher ----
echo "[4] Updating field launcher..."
REPO_DIR=""
for d in ~/uconsole-field-kit /opt/uconsole-field-kit /tmp/uconsole-field-kit; do
    [[ -d "$d/.git" ]] && REPO_DIR="$d" && break
done
if [[ -n "$REPO_DIR" ]]; then
    cd "$REPO_DIR"
    git pull 2>/dev/null || true
    install -m 0755 scripts/field-launcher.py /usr/local/bin/field-launcher
    echo "  Launcher updated from $REPO_DIR"
    
    # Install desktop icon
    mkdir -p ~/.local/share/applications 2>/dev/null
    cp systemd/field-launcher.desktop ~/.local/share/applications/ 2>/dev/null || true
    echo "  Desktop icon installed"
else
    echo "  Repo not found. Run: git clone https://github.com/blackwellj/uconsole-field-kit.git"
fi
echo

# ---- Fix 5: Install power button watchdog ----
echo "[5] Installing power button watchdog..."
if [[ -f "$REPO_DIR/scripts/power-button-watchdog.py" ]]; then
    install -m 0755 "$REPO_DIR/scripts/power-button-watchdog.py" /usr/local/sbin/uconsole-power-watchdog
    cat > /etc/systemd/system/uconsole-power-watchdog.service <<'UNIT'
[Unit]
Description=uConsole power button hardware watchdog
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/local/sbin/uconsole-power-watchdog
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl enable --now uconsole-power-watchdog
    echo "  Watchdog installed and enabled (10s hold = force poweroff)"
else
    echo "  Watchdog script not found in repo"
fi
echo

# ---- Fix 6: Fix EEPROM power settings ----
echo "[6] Checking EEPROM..."
if command -v rpi-eeprom-config >/dev/null 2>&1; then
    CURRENT=$(rpi-eeprom-config 2>/dev/null)
    if echo "$CURRENT" | grep -q 'POWER_OFF_ON_HALT=1'; then
        echo "  POWER_OFF_ON_HALT=1 found — fixing to 0..."
        TMP=$(mktemp)
        rpi-eeprom-config > "$TMP"
        sed -i 's/^POWER_OFF_ON_HALT=.*/POWER_OFF_ON_HALT=0/' "$TMP"
        rpi-eeprom-config --apply "$TMP"
        rm -f "$TMP"
        echo "  Fixed: POWER_OFF_ON_HALT=0 (reboots will work now)"
    else
        echo "  POWER_OFF_ON_HALT already 0 or not set — OK"
    fi
    if echo "$CURRENT" | grep -q 'BOOT_ORDER=0xf461'; then
        echo "  BOOT_ORDER=0xf461 (NVMe first) — fixing to 0xf641 (SD first)..."
        TMP=$(mktemp)
        rpi-eeprom-config > "$TMP"
        sed -i 's/^BOOT_ORDER=.*/BOOT_ORDER=0xf641/' "$TMP"
        rpi-eeprom-config --apply "$TMP"
        rm -f "$TMP"
        echo "  Fixed: BOOT_ORDER=0xf641 (SD → USB → NVMe)"
    else
        echo "  BOOT_ORDER looks OK"
    fi
fi
echo

# ---- Fix 7: Install uconsole-radio and uconsole-doctor ----
echo "[7] Installing scripts..."
if [[ -n "$REPO_DIR" ]]; then
    install -m 0755 "$REPO_DIR/scripts/uconsole-radio" /usr/local/bin/uconsole-radio 2>/dev/null && echo "  uconsole-radio installed" || true
    install -m 0755 "$REPO_DIR/scripts/uconsole-doctor" /usr/local/bin/uconsole-doctor 2>/dev/null && echo "  uconsole-doctor installed" || true
    install -m 0755 "$REPO_DIR/scripts/uconsole-display" /usr/local/bin/uconsole-display 2>/dev/null && echo "  uconsole-display installed" || true
fi
echo

# ---- Fix 8: Kill old launcher and start new one ----
echo "[8] Restarting launcher..."
pkill -f field-launcher 2>/dev/null || true
sleep 1
# Start it in the background on the display
export DISPLAY=:0
python3 /usr/local/bin/field-launcher &
echo "  Launcher started"
echo

echo "================================================================"
echo " Done. What to check:"
echo "================================================================"
echo " 1. Is the screen showing the launcher now?"
echo " 2. Try: ssh james@clockworkpi.local (should work)"
echo " 3. Try: holding power button 10s (should force poweroff once watchdog loads)"
echo " 4. Look for 'Field Launcher' in the app menu"
echo
echo " If screen still black, try:"
echo "   sudo sh -c 'echo 255 > /sys/class/backlight/*/brightness'"
echo "   sudo systemctl restart display-manager"
