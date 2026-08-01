#!/usr/bin/env python3
"""
uConsole power button hardware watchdog.

Monitors the power button input device. If the button is held
continuously for 10 seconds, force poweroff — regardless of whether
the display daemon or logind is working. This is the safety net that
ensures you can always power off without pulling the battery.
"""
import time
import os
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HOLD_SECONDS = 10
POWER_KEY = 197  # KEY_POWER

def find_power_device():
    """Find an input device that reports KEY_POWER."""
    try:
        from evdev import InputDevice, list_devices, ecodes
    except ImportError:
        logging.error("evdev not installed — watchdog unavailable")
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
    from evdev import InputDevice, ecodes, select

    path = find_power_device()
    if not path:
        logging.warning("No power button device found. Watchdog inactive.")
        return

    dev = InputDevice(path)
    logging.info("Power button watchdog active on %s (hold %ds to force poweroff)", path, HOLD_SECONDS)

    held_since = None

    while True:
        try:
            readable, _, _ = select([dev], [], [])
            for event in dev.read():
                if event.type == ecodes.EV_KEY and event.code == ecodes.KEY_POWER:
                    if event.value == 1:  # pressed
                        held_since = time.monotonic()
                        logging.info("Power button pressed")
                    elif event.value == 0:  # released
                        if held_since is not None:
                            duration = time.monotonic() - held_since
                            logging.info("Power button released after %.1fs", duration)
                        held_since = None

            # Check hold duration
            if held_since is not None:
                duration = time.monotonic() - held_since
                if duration >= HOLD_SECONDS:
                    logging.warning("Power button held for %.1fs — FORCING POWEROFF", duration)
                    # Sync filesystems then power off immediately
                    subprocess.run("sync", shell=True)
                    subprocess.run("sudo systemctl poweroff -f --force", shell=True)
                    time.sleep(2)
                    # If systemctl didn't work, write directly to reboot syscall
                    try:
                        with open("/proc/sysrq-trigger", "w") as f:
                            f.write("o")  # 'o' = poweroff
                    except Exception:
                        pass
                    os.system("sudo poweroff -f")
                    time.sleep(5)
                    os._exit(0)

        except OSError as exc:
            logging.warning("Device error: %s — reconnecting...", exc)
            time.sleep(2)
            path = find_power_device()
            if path:
                dev = InputDevice(path)
            time.sleep(1)
        except Exception as exc:
            logging.error("Watchdog error: %s", exc)
            time.sleep(2)

if __name__ == "__main__":
    main()
