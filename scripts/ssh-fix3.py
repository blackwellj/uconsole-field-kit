#!/usr/bin/env python3
"""Fix round 3: x11vnc BadMatch, launcher, final check."""
import subprocess

HOST = "james@clockworkpi.local"
PASS = "S4lcombe2!\n"

remote = r"""
echo "=== FIX VNC: BadMatch means display not ready yet ==="
# x11vnc gets BadMatch when the X server hasn't fully initialised.
# Add a longer delay and use -noxrecord to avoid the GetImage error.
XAUTH=/home/james/.Xauthority
cat > /etc/systemd/system/x11vnc.service << UNIT
[Unit]
Description=x11vnc VNC server (shares physical display)
After=graphical.target
Requires=graphical.target

[Service]
Type=simple
Environment=DISPLAY=:0
Environment=XAUTHORITY=$XAUTH
ExecStartPre=/bin/sh -c 'sleep 10'
ExecStart=/usr/bin/x11vnc -display :0 -auth $XAUTH -rfbauth /etc/x11vnc.pass -rfbport 5900 -shared -forever -noxrecord -noxdamage -o /var/log/x11vnc.log
Restart=on-failure
RestartSec=10

[Install]
WantedBy=graphical.target
UNIT
systemctl daemon-reload
systemctl restart x11vnc

echo "=== START LAUNCHER ==="
pkill -f field-launcher 2>/dev/null || true
sleep 1
sudo -u james env DISPLAY=:0 XAUTHORITY=/home/james/.Xauthority python3 /usr/local/bin/field-launcher &
sleep 3

echo "=== FINAL STATUS ==="
for svc in ssh x11vnc uconsole-power-button uconsole-power-watchdog gpsd chrony aiov2-rails-boot; do
    echo "$svc: $(systemctl is-active $svc 2>/dev/null)"
done
echo "aiov2_ctl: $(which aiov2_ctl 2>/dev/null)"
echo "aiov2 status:"
aiov2_ctl 2>/dev/null
echo "Launcher: $(pgrep -a field-launcher 2>/dev/null || echo 'not running')"
echo "Backlight: $(cat /sys/class/backlight/backlight@0/brightness 2>/dev/null)/$(cat /sys/class/backlight/backlight@0/max_brightness 2>/dev/null)"
echo "EEPROM:"
rpi-eeprom-config 2>/dev/null | grep -E 'BOOT_ORDER|POWER_OFF'
echo "=== DONE ==="
"""

proc = subprocess.Popen(
    ["ssh", "-o", "StrictHostKeyChecking=no", HOST,
     "sudo bash -c '" + remote.replace("'", "'\\''") + "'"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)
out, err = proc.communicate(input=PASS, timeout=60)
print(out)
if err:
    print("ERR:", err[:500])
