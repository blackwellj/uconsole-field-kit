#!/bin/bash
# Fix everything on the uConsole
set -x

echo "=== FIX 1: VNC for Xwayland ==="
# x11vnc gets BadMatch on Xwayland rootless mode.
# Use -noxdamage -threads and add -nocursorshape
# If it still fails, we'll try a different approach.
sudo tee /etc/systemd/system/x11vnc.service > /dev/null << 'UNIT'
[Unit]
Description=x11vnc VNC server
After=graphical.target
Requires=graphical.target
[Service]
Type=simple
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/james/.Xauthority
ExecStartPre=/bin/sh -c 'sleep 10'
ExecStart=/usr/bin/x11vnc -display :0 -auth /home/james/.Xauthority -rfbauth /etc/x11vnc.pass -rfbport 5900 -shared -forever -threads -noxdamage -nosel -noprimary -nocursorshape -nowf -o /var/log/x11vnc.log
Restart=on-failure
RestartSec=10
[Install]
WantedBy=graphical.target
UNIT
sudo systemctl daemon-reload
sudo systemctl restart x11vnc

echo "=== FIX 2: Enable AIO rails ==="
sudo systemctl enable --now aiov2-rails-boot 2>/dev/null || true
sleep 2
aiov2_ctl GPS on 2>/dev/null || true
aiov2_ctl SDR on 2>/dev/null || true
aiov2_ctl USB on 2>/dev/null || true
aiov2_ctl LORA on 2>/dev/null || true
sleep 1
echo "AIO state:"
aiov2_ctl 2>/dev/null

echo "=== FIX 3: Start launcher ==="
rm -f /tmp/launcher.log
sudo -u james touch /tmp/launcher.log
pkill -f field-launcher 2>/dev/null || true
sleep 1
mkdir -p /run/user/1000
chmod 700 /run/user/1000
sudo chown james:james /run/user/1000
sudo -u james env DISPLAY=:0 XAUTHORITY=/home/james/.Xauthority XDG_RUNTIME_DIR=/run/user/1000 nohup python3 /usr/local/bin/field-launcher > /tmp/launcher.log 2>&1 &
sleep 5
pgrep -a field-launcher && echo "LAUNCHER-OK" || { echo "LAUNCHER-FAILED"; cat /tmp/launcher.log; }

echo "=== FIX 4: Install SSH key for passwordless access ==="
mkdir -p /home/james/.ssh
# Add the framework key to authorized_keys
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIc+VXOyr1j92lJyGxjXF4ylym7ffzK/tkb2Dkl7wezd black@Framework" >> /home/james/.ssh/authorized_keys 2>/dev/null || true
sort -u -o /home/james/.ssh/authorized_keys /home/james/.ssh/authorized_keys 2>/dev/null || true
chmod 700 /home/james/.ssh
chmod 600 /home/james/.ssh/authorized_keys
sudo chown -R james:james /home/james/.ssh
echo "SSH key installed"

echo "=== WAIT AND CHECK VNC ==="
sleep 12
echo "VNC status: $(systemctl is-active x11vnc 2>/dev/null)"
tail -5 /var/log/x11vnc.log 2>/dev/null

echo "=== FINAL STATUS ==="
for svc in ssh x11vnc uconsole-power-button uconsole-power-watchdog gpsd chrony aiov2-rails-boot; do
    echo "$svc: $(systemctl is-active $svc 2>/dev/null)"
done
echo "aiov2: $(aiov2_ctl 2>/dev/null | tr '\n' ' ')"
echo "Launcher: $(pgrep -a field-launcher 2>/dev/null || echo not-running)"
echo "Backlight: $(cat /sys/class/backlight/backlight@0/brightness 2>/dev/null)/9"
echo "EEPROM:"
rpi-eeprom-config 2>/dev/null | grep -E 'BOOT_ORDER|POWER_OFF'
echo "=== DONE ==="
