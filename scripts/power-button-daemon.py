#!/usr/bin/env python3
from __future__ import annotations

import glob
import logging
import os
import subprocess
import time
from pathlib import Path

from evdev import InputDevice, ecodes, list_devices, select

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def candidate_devices() -> list[str]:
    paths = list_devices()
    preferred: list[str] = []
    others: list[str] = []
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

def main() -> None:
    while True:
        devices = candidate_devices()
        if not devices:
            logging.warning("No input device advertising KEY_POWER was found.")
            time.sleep(10)
            continue

        opened = [InputDevice(path) for path in devices]
        logging.info("Watching power button devices: %s", ", ".join(d.path for d in opened))
        try:
            while True:
                readable, _, _ = select(opened, [], [])
                for dev in readable:
                    for event in dev.read():
                        if event.type == ecodes.EV_KEY and event.code == ecodes.KEY_POWER and event.value == 0:
                            subprocess.run(
                                ["/usr/local/bin/uconsole-display", "toggle"],
                                check=False,
                            )
        except OSError as exc:
            logging.warning("Input device disappeared: %s", exc)
        finally:
            for dev in opened:
                dev.close()
        time.sleep(2)

if __name__ == "__main__":
    main()
