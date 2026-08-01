#!/usr/bin/env python3
"""Fix VNC and launcher - copy script to uConsole and run it."""
import subprocess, base64

HOST = "james@clockworkpi.local"
PASS = "S4lcombe2!\n"

# The script to run on the uConsole, base64-encoded to avoid quoting hell
script = r"""#!/bin/bash
# Fix VNC
cat > /etc/systemd/system/x11vnc.service << 'SVCEOF'
[Unit]
Description=x11vnc VNC server
After=graphical.target
Requires=graphical.target
[Service]
Type=simple
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/james/.Xauthority
ExecStartPre=/bin/sh -c 'sleep 10'
ExecStart=/usr/bin/x11vnc -display :0 -auth /home/james/.Xauthority -rfbauth /etc/x11vnc.pass -rfbport 5900 -shared -forever -noxrecord -noxdamage -o /var/log/x11vnc.log
Restart=on-failure
RestartSec=10
[Install]
WantedBy=graphical.target
SVCEOF
systemctl daemon-reload
systemctl restart x11vnc

# Start launcher
pkill -f field-launcher 2>/dev/null || true
sleep 1
sudo -u james env DISPLAY=:0 XAUTHORITY=/home/james/.Xauthority nohup python3 /usr/local/bin/field-launcher > /tmp/launcher.log 2>&1 &
sleep 3

# Report
echo "=== STATUS ==="
for svc in ssh x11vnc uconsole-power-button uconsole-power-watchdog gpsd chrony aiov2-rails-boot; do
    echo "$svc: $(systemctl is-active $svc 2>/dev/null)"
done
echo "aiov2_ctl: $(which aiov2_ctl 2>/dev/null)"
aiov2_ctl 2>/dev/null
echo "Launcher: $(pgrep -a field-launcher 2>/dev/null || echo not-running)"
tail -3 /tmp/launcher.log 2>/dev/null
echo "Backlight: $(cat /sys/class/backlight/backlight@0/brightness 2>/dev/null)/9"
echo "=== DONE ==="
"""

# Base64 encode the script
b64 = base64.b64encode(script.encode()).decode()

# SSH in, decode and run the script
remote_cmd = f"echo {b64} | base64 -d | sudo bash"

proc = subprocess.Popen(
    ["ssh", "-o", "StrictHostKeyChecking=no", HOST, remote_cmd],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)
out, err = proc.communicate(input=PASS, timeout=45)
print(out)
if err:
    print("ERR:", err[:300])
