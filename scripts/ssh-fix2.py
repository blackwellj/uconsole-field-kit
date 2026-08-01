#!/usr/bin/env python3
"""Fix round 2: aiov2_ctl, x11vnc, launcher."""
import subprocess

HOST = "james@clockworkpi.local"
PASS = "S4lcombe2!\n"

remote = r"""
echo "=== FIX A: Install aiov2_ctl ==="
rm -rf /opt/aiov2_ctl
git clone --depth 1 https://github.com/hackergadgets/aiov2_ctl.git /opt/aiov2_ctl 2>&1
python3 /opt/aiov2_ctl/aiov2_ctl.py --install 2>&1
which aiov2_ctl 2>/dev/null && echo "aiov2_ctl OK" || echo "aiov2_ctl still not found"
echo "---AIOFIX---"

echo "=== FIX B: x11vnc auth ==="
# x11vnc needs access to the X authority file
# Find the .Xauthority file
XAUTH=$(find /home -name .Xauthority -type f 2>/dev/null | head -1)
echo "XAUTH=$XAUTH"
cat > /etc/systemd/system/x11vnc.service << UNIT
[Unit]
Description=x11vnc VNC server (shares physical display)
After=graphical.target
Requires=graphical.target

[Service]
Type=simple
Environment=DISPLAY=:0
Environment=XAUTHORITY=$XAUTH
ExecStartPre=/bin/sh -c 'sleep 5'
ExecStart=/usr/bin/x11vnc -display :0 -auth $XAUTH -rfbauth /etc/x11vnc.pass -rfbport 5900 -shared -forever -o /var/log/x11vnc.log
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical.target
UNIT
systemctl daemon-reload
systemctl restart x11vnc
sleep 3
systemctl is-active x11vnc && echo "x11vnc OK" || echo "x11vnc still failing"
tail -5 /var/log/x11vnc.log 2>/dev/null
echo "---VNCFIX---"

echo "=== FIX C: Start launcher ==="
export DISPLAY=:0
export XAUTHORITY=/home/james/.Xauthority
pkill -f field-launcher 2>/dev/null || true
sleep 1
nohup sudo -u james env DISPLAY=:0 XAUTHORITY=/home/james/.Xauthority python3 /usr/local/bin/field-launcher > /tmp/launcher.log 2>&1 &
sleep 2
pgrep -a field-launcher && echo "launcher OK" || echo "launcher failed to start"
cat /tmp/launcher.log 2>/dev/null | tail -5
echo "---LAUNCHERFIX---"

echo "=== FINAL STATUS ==="
for svc in ssh x11vnc uconsole-power-button uconsole-power-watchdog gpsd chrony; do
    echo "$svc: $(systemctl is-active $svc 2>/dev/null)"
done
echo "aiov2_ctl: $(which aiov2_ctl 2>/dev/null || echo 'not found')"
echo "Launcher: $(pgrep -a field-launcher 2>/dev/null || echo 'not running')"
echo "Backlight: $(cat /sys/class/backlight/backlight@0/brightness 2>/dev/null)/$(cat /sys/class/backlight/backlight@0/max_brightness 2>/dev/null)"
echo "=== DONE ==="
"""

proc = subprocess.Popen(
    ["ssh", "-o", "StrictHostKeyChecking=no", HOST,
     "sudo bash -c '" + remote.replace("'", "'\\''") + "'"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)
out, err = proc.communicate(input=PASS, timeout=120)
print(out)
if err:
    print("ERR:", err[:500])
