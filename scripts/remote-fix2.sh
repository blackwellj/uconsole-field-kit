#!/bin/bash
# Fix launcher log path and disable broken VNC
pkill -f field-launcher 2>/dev/null || true
sleep 1
sudo -u james env DISPLAY=:0 XAUTHORITY=/home/james/.Xauthority XDG_RUNTIME_DIR=/run/user/1000 nohup python3 /usr/local/bin/field-launcher > /home/james/launcher.log 2>&1 &
sleep 5
pgrep -a field-launcher && echo "LAUNCHER-OK" || { echo "LAUNCHER-FAILED"; cat /home/james/launcher.log; }

# VNC: x11vnc doesn't work with Xwayland rootless (BadMatch on X_GetImage)
# Disable for now - needs wayvnc or Xorg session
sudo systemctl stop x11vnc 2>/dev/null || true
sudo systemctl disable x11vnc 2>/dev/null || true
echo "VNC disabled (x11vnc incompatible with Xwayland rootless)"

# EEPROM needs reboot to apply
echo "EEPROM: 0xf641 staged, needs reboot to apply"

echo "=== FINAL ==="
echo "Launcher: $(pgrep -a field-launcher 2>/dev/null || echo not-running)"
echo "AIO: $(aiov2_ctl 2>/dev/null | tr '\n' ' ')"
echo "Backlight: $(cat /sys/class/backlight/backlight@0/brightness 2>/dev/null)/9"
echo "Power button: $(systemctl is-active uconsole-power-button 2>/dev/null)"
echo "Watchdog: $(systemctl is-active uconsole-power-watchdog 2>/dev/null)"
echo "SSH: $(systemctl is-active ssh 2>/dev/null)"
echo "GPSd: $(systemctl is-active gpsd 2>/dev/null)"
echo "Chrony: $(systemctl is-active chrony 2>/dev/null)"
echo "=== DONE ==="
