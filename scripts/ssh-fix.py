#!/usr/bin/env python3
"""Fix everything on the uConsole via SSH."""
import subprocess, sys, time

HOST = "james@clockworkpi.local"
PASS = "S4lcombe2!\n"

remote = r"""
set -e

echo "=== FIX 1: Power button daemon (evdev select import) ==="
# The daemon uses 'from evdev import select' which doesn't exist.
# Fix: use Python's built-in select module instead.
cat > /usr/local/sbin/uconsole-power-button-daemon << 'PYEOF'
#!/usr/bin/env python3
from __future__ import annotations
import glob, logging, os, subprocess, time
from pathlib import Path
from evdev import InputDevice, ecodes, list_devices
import select as select_mod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def candidate_devices():
    paths = list_devices()
    preferred, others = [], []
    for path in paths:
        try:
            dev = InputDevice(path)
            name = dev.name.lower()
            caps = dev.capabilities()
            keys = caps.get(ecodes.EV_KEY, [])
            if ecodes.KEY_POWER not in keys:
                continue
            if "gpio" in name or "power" in name:
                preferred.append(path)
            else:
                others.append(path)
        except OSError:
            continue
    return preferred + others

def main():
    while True:
        devices = candidate_devices()
        if not devices:
            logging.warning("No power button device found.")
            time.sleep(10)
            continue
        opened = [InputDevice(path) for path in devices]
        logging.info("Watching: %s", ", ".join(d.path for d in opened))
        try:
            while True:
                readable, _, _ = select_mod.select(opened, [], [])
                for dev in readable:
                    for event in dev.read():
                        if event.type == ecodes.EV_KEY and event.code == ecodes.KEY_POWER and event.value == 0:
                            subprocess.run(["/usr/local/bin/uconsole-display", "toggle"], check=False)
        except OSError as exc:
            logging.warning("Device disappeared: %s", exc)
        finally:
            for dev in opened:
                dev.close()
        time.sleep(2)

if __name__ == "__main__":
    main()
PYEOF
chmod +x /usr/local/sbin/uconsole-power-button-daemon
systemctl restart uconsole-power-button
echo "  Fixed: power button daemon restarted"

echo "=== FIX 2: x11vnc (no DISPLAY in service) ==="
cat > /etc/systemd/system/x11vnc.service << 'UNIT'
[Unit]
Description=x11vnc VNC server (shares physical display)
After=graphical.target
Requires=graphical.target

[Service]
Type=simple
Environment=DISPLAY=:0
ExecStartPre=/bin/sh -c 'sleep 3'
ExecStart=/usr/bin/x11vnc -display :0 -rfbauth /etc/x11vnc.pass -rfbport 5900 -shared -forever -o /var/log/x11vnc.log
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical.target
UNIT
systemctl daemon-reload
systemctl restart x11vnc
echo "  Fixed: x11vnc service with DISPLAY=:0"

echo "=== FIX 3: aiov2_ctl PATH ==="
# Find where it actually is
AIO_PATH=$(find /usr -name aiov2_ctl -type f 2>/dev/null | head -1)
if [ -z "$AIO_PATH" ]; then
    AIO_PATH=$(find /opt -name aiov2_ctl -type f 2>/dev/null | head -1)
fi
if [ -n "$AIO_PATH" ]; then
    ln -sf "$AIO_PATH" /usr/local/bin/aiov2_ctl
    echo "  Fixed: symlinked aiov2_ctl from $AIO_PATH"
else
    echo "  aiov2_ctl not found anywhere - may need reinstall"
fi

echo "=== FIX 4: EEPROM boot order ==="
TMP=$(mktemp)
rpi-eeprom-config > "$TMP"
sed -i 's/^BOOT_ORDER=.*/BOOT_ORDER=0xf641/' "$TMP"
rpi-eeprom-config --apply "$TMP"
rm -f "$TMP"
echo "  Fixed: BOOT_ORDER=0xf641 (SD -> USB -> NVMe)"

echo "=== FIX 5: Install power button watchdog ==="
cat > /usr/local/sbin/uconsole-power-watchdog << 'PYEOF'
#!/usr/bin/env python3
import time, os, subprocess, logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
HOLD_SECONDS = 10
def find_power_device():
    try:
        from evdev import InputDevice, list_devices, ecodes
    except ImportError:
        return None
    for path in list_devices():
        try:
            dev = InputDevice(path)
            caps = dev.capabilities()
            keys = caps.get(ecodes.EV_KEY, [])
            if ecodes.KEY_POWER in keys:
                return path
        except OSError:
            continue
    return None
def main():
    from evdev import InputDevice, ecodes
    import select as select_mod
    path = find_power_device()
    if not path:
        logging.warning("No power button device found.")
        return
    dev = InputDevice(path)
    logging.info("Watchdog active on %s", path)
    held_since = None
    while True:
        try:
            readable, _, _ = select_mod.select([dev], [], [])
            for event in dev.read():
                if event.type == ecodes.EV_KEY and event.code == ecodes.KEY_POWER:
                    if event.value == 1:
                        held_since = time.monotonic()
                    elif event.value == 0:
                        held_since = None
            if held_since is not None and time.monotonic() - held_since >= HOLD_SECONDS:
                logging.warning("Force poweroff!")
                subprocess.run("sync", shell=True)
                subprocess.run("systemctl poweroff -f", shell=True)
                time.sleep(2)
                try:
                    with open("/proc/sysrq-trigger", "w") as f:
                        f.write("o")
                except Exception:
                    pass
                os._exit(0)
        except OSError:
            time.sleep(2)
            path = find_power_device()
            if path:
                dev = InputDevice(path)
        except Exception:
            time.sleep(2)
if __name__ == "__main__":
    main()
PYEOF
chmod +x /usr/local/sbin/uconsole-power-watchdog
cat > /etc/systemd/system/uconsole-power-watchdog.service << 'UNIT'
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
echo "  Fixed: watchdog installed (10s hold = force poweroff)"

echo "=== FIX 6: Update field launcher ==="
cd /home/james/uconsole-field-kit 2>/dev/null || cd /tmp
git pull 2>/dev/null || true
if [ -f scripts/field-launcher.py ]; then
    install -m 0755 scripts/field-launcher.py /usr/local/bin/field-launcher
    echo "  Fixed: launcher updated"
fi
# Install desktop icon
mkdir -p /home/james/.local/share/applications
cp systemd/field-launcher.desktop /home/james/.local/share/applications/ 2>/dev/null || true
chown -R james:james /home/james/.local/share/applications

echo "=== FIX 7: Restart launcher ==="
pkill -f field-launcher 2>/dev/null || true
sleep 1
export DISPLAY=:0
nohup python3 /usr/local/bin/field-launcher > /dev/null 2>&1 &
echo "  Fixed: launcher started"

echo "=== FIX 8: Verify everything ==="
sleep 2
echo "Services:"
for svc in ssh x11vnc uconsole-power-button uconsole-power-watchdog gpsd chrony; do
    echo "  $svc: $(systemctl is-active $svc 2>/dev/null)"
done
echo "Backlight: $(cat /sys/class/backlight/backlight@0/brightness 2>/dev/null)/$(cat /sys/class/backlight/backlight@0/max_brightness 2>/dev/null)"
echo "aiov2_ctl: $(which aiov2_ctl 2>/dev/null || echo 'not found')"
echo "Launcher PID: $(pgrep -f field-launcher 2>/dev/null || echo 'not running')"

echo "=== ALL FIXES DONE ==="
"""

proc = subprocess.Popen(
    ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
     HOST, "sudo bash -c '" + remote.replace("'", "'\\''") + "'"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)

try:
    out, err = proc.communicate(input=PASS, timeout=60)
    print(out)
    if err:
        print("STDERR:", err[:500])
except subprocess.TimeoutExpired:
    print("TIMEOUT - still running")
    proc.kill()
