#!/usr/bin/env python3
"""Fix launcher startup and check VNC."""
import subprocess, base64

HOST = "james@clockworkpi.local"
PASS = "S4lcombe2!\n"

script = r"""#!/bin/bash
# Fix launcher - needs XDG_RUNTIME_DIR
mkdir -p /run/user/1000
chmod 700 /run/user/1000
chown james:james /run/user/1000

pkill -f field-launcher 2>/dev/null || true
sleep 1

# Start as james with proper env
sudo -u james env \
    DISPLAY=:0 \
    XAUTHORITY=/home/james/.Xauthority \
    XDG_RUNTIME_DIR=/run/user/1000 \
    nohup python3 /usr/local/bin/field-launcher > /tmp/launcher.log 2>&1 &

sleep 4
pgrep -a field-launcher && echo "LAUNCHER-OK" || echo "LAUNCHER-FAILED"
cat /tmp/launcher.log 2>/dev/null | tail -10

# Check VNC after the 10s delay should have passed
sleep 8
echo "VNC: $(systemctl is-active x11vnc 2>/dev/null)"
tail -5 /var/log/x11vnc.log 2>/dev/null

echo DONE
"""

b64 = base64.b64encode(script.encode()).decode()
remote_cmd = f"echo {b64} | base64 -d | sudo bash"

proc = subprocess.Popen(
    ["ssh", "-o", "StrictHostKeyChecking=no", HOST, remote_cmd],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)
out, err = proc.communicate(input=PASS, timeout=45)
print(out)
if err:
    print("ERR:", err[:300])
