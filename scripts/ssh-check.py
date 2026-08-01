#!/usr/bin/env python3
"""Check uConsole status and install aiov2_ctl."""
import subprocess

HOST = "james@clockworkpi.local"
PASS = "S4lcombe2!\n"

remote = r"""
echo "=== STATUS CHECK ==="
for svc in ssh x11vnc uconsole-power-button uconsole-power-watchdog gpsd chrony display-manager; do
    echo "$svc: $(systemctl is-active $svc 2>/dev/null)"
done
echo "---"

echo "Backlight: $(cat /sys/class/backlight/backlight@0/brightness 2>/dev/null)/$(cat /sys/class/backlight/backlight@0/max_brightness 2>/dev/null)"
echo "---"

echo "Launcher: $(pgrep -a field-launcher 2>/dev/null || echo 'not running')"
echo "---"

echo "aiov2_ctl: $(which aiov2_ctl 2>/dev/null || echo 'not in PATH')"
ls -la /usr/local/bin/aiov2_ctl 2>/dev/null || echo "no symlink"
ls -la /opt/aiov2_ctl/aiov2_ctl.py 2>/dev/null || echo "not in /opt"
python3 /opt/aiov2_ctl/aiov2_ctl.py 2>/dev/null || echo "can't run from /opt"
echo "---"

echo "pinctrl: $(which pinctrl 2>/dev/null || echo 'not found')"
echo "---"

echo "VNC log tail:"
tail -3 /var/log/x11vnc.log 2>/dev/null || echo "no log"
echo "---"

echo "Power button log:"
journalctl -u uconsole-power-button --no-pager -n 3 2>&1
echo "---"

echo "Watchdog log:"
journalctl -u uconsole-power-watchdog --no-pager -n 3 2>&1
echo "---"

echo "ENDCHECK"
"""

proc = subprocess.Popen(
    ["ssh", "-o", "StrictHostKeyChecking=no", HOST,
     "sudo bash -c '" + remote.replace("'", "'\\''") + "'"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)
out, err = proc.communicate(input=PASS, timeout=30)
print(out)
if err:
    print("ERR:", err[:300])
