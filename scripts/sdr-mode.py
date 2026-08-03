#!/usr/bin/env python3
"""
uConsole SDR Mode Switcher — manages the single RTL-SDR between decode modes.

Modes:
  pager   — RNLI POCSAG decoding (153.075 MHz) via multimon-ng → CoastalHub
  ais     — AIS vessel tracking (161.975/162.025 MHz) via AIS-catcher → CoastalHub
  dsc     — DSC distress decoding (156.525 MHz, Ch 70) via multimon-ng → CoastalHub
  scanner — Radio scanner via rdio-scanner
  off     — SDR released, no decoding

Usage:
  sdr-mode pager   # switch to pager mode
  sdr-mode ais     # switch to AIS mode
  sdr-mode dsc     # switch to DSC mode
  sdr-mode scanner # switch to scanner mode
  sdr-mode off     # stop all
  sdr-mode status  # current mode
"""

import subprocess
import sys
import os
import time
import json
import signal
import logging
import urllib.request
import urllib.parse
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sdr-mode")

STATE_FILE = "/run/sdr-mode.json"
CONFIG_FILE = "/etc/coastalhub/node.conf"
FREQS = {"pager": 153.075, "ais": 161.975, "dsc": 156.525}

def load_config():
    """Load CoastalHub node config."""
    cfg = {}
    try:
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    except Exception:
        pass
    return cfg

def submit_pagermon(address, message, source):
    """Submit a pager message to PagerMon/CoastalHub."""
    cfg = load_config()
    url = cfg.get("PAGERMON_URL", "https://pager.coastalhub.uk") + "/api/messages"
    apikey = cfg.get("PAGERMON_APIKEY", "")
    data = urllib.parse.urlencode({
        "address": address,
        "message": message,
        "datetime": str(int(time.time())),
        "source": source or cfg.get("NODE_NAME", "uConsole"),
    }).encode()
    try:
        req = urllib.request.Request(url, data=data, headers={
            "apikey": apikey,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        log.info("PagerMon submitted: %s -> %d", message[:40], resp.status)
    except Exception as e:
        log.warning("PagerMon submit failed: %s", e)

def submit_dsc(payload):
    """Submit a DSC event to CoastalHub."""
    cfg = load_config()
    url = cfg.get("COASTALHUB_URL", "https://coastalhub.uk") + "/api/dsc/webhook"
    token = cfg.get("COASTALHUB_DSC_TOKEN", "")
    data = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        log.info("DSC submitted: %d", resp.status)
    except Exception as e:
        log.warning("DSC submit failed: %s", e)

def sh(cmd, timeout=5):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""

def which(cmd):
    return sh(f"command -v {cmd}") != ""

def get_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"mode": "off", "pid": None}

def save_state(mode, pid=None):
    with open(STATE_FILE, "w") as f:
        json.dump({"mode": mode, "pid": pid, "time": time.time()}, f)

def kill_pid(pid):
    if pid and pid > 0:
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            # Force kill if still alive
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        except ProcessLookupError:
            pass

def kill_all_sdr_processes():
    """Kill any running SDR decoder processes."""
    for proc in ["multimon-ng", "ais-catcher", "rtl_fm", "rtl_433", "readsb", "dump1090"]:
        sh(f"pkill -f {proc} 2>/dev/null")
    time.sleep(0.5)

def ensure_sdr_on():
    """Make sure the AIO SDR module is powered on."""
    if which("aiov2_ctl"):
        sh("sudo -n aiov2_ctl SDR on 2>/dev/null")
        time.sleep(1)

def parse_multimon_pager(proc, source_name):
    """Parse multimon-ng POCSAG output and submit to PagerMon/CoastalHub."""
    for line in proc.stdout:
        line = line.decode("utf-8", errors="replace").strip()
        if "POCSAG" in line and "Address:" in line and "Alpha:" in line:
            try:
                addr_part = line.split("Address:")[1].split("Function")[0].strip()
                msg_part = line.split("Alpha:")[1].strip() if "Alpha:" in line else ""
                if addr_part and msg_part:
                    address = addr_part.zfill(7)
                    msg = msg_part.replace("<NUL>", "").strip()
                    log.info("POCSAG: addr=%s msg=%s", address, msg[:60])
                    submit_pagermon(address, msg, source_name)
            except Exception as e:
                log.debug("Parse error: %s", e)

def start_pager():
    """Start POCSAG pager decoding via multimon-ng → CoastalHub."""
    ensure_sdr_on()
    freq = FREQS["pager"]
    cfg = load_config()
    source = cfg.get("NODE_NAME", "uConsole")
    cmd = (
        f"rtl_fm -f {freq}M -s 22050 -l 0 -g 40 -E DC 2>/dev/null | "
        f"multimon-ng -t raw -a POCSAG512 -a POCSAG1200 -a POCSAG2400 -f alpha - 2>/dev/null"
    )
    proc = subprocess.Popen(cmd, shell=True, start_new_session=True,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    # Start parser thread
    import threading
    t = threading.Thread(target=parse_multimon_pager, args=(proc, source), daemon=True)
    t.start()
    save_state("pager", proc.pid)
    log.info("Pager mode started on %.3f MHz (PID %d) → CoastalHub", freq, proc.pid)
    return proc

def start_ais():
    """Start AIS vessel tracking via AIS-catcher."""
    ensure_sdr_on()
    if not which("ais-catcher"):
        # Fallback to rtl_ais
        if which("rtl_ais"):
            cmd = "rtl_ais -n 2>/dev/null"
        else:
            log.error("Neither ais-catcher nor rtl_ais installed")
            save_state("off")
            return None
    else:
        # AIS-catcher with JSON output to stdout
        cmd = "ais-catcher -r 96000 -g 40 -s 2>/dev/null"
    proc = subprocess.Popen(cmd, shell=True, start_new_session=True,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    save_state("ais", proc.pid)
    log.info("AIS mode started (PID %d)", proc.pid)
    return proc

def start_dsc():
    """Start DSC distress decoding on Ch 70 (156.525 MHz) via multimon-ng."""
    ensure_sdr_on()
    freq = FREQS["dsc"]
    # DSC uses FSK modulation. multimon-ng can decode it with -a DSC
    # Feed rtl_fm at the DSC frequency to multimon-ng
    cmd = (
        f"rtl_fm -f {freq}M -s 22050 -l 0 -g 40 -E DC 2>/dev/null | "
        f"multimon-ng -t raw -a DSC -f alpha - 2>/dev/null"
    )
    proc = subprocess.Popen(cmd, shell=True, start_new_session=True,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    save_state("dsc", proc.pid)
    log.info("DSC mode started on %.3f MHz (PID %d)", freq, proc.pid)
    return proc

def start_scanner():
    """Start rdio-scanner for general radio monitoring."""
    ensure_sdr_on()
    if not which("rdio-scanner"):
        log.error("rdio-scanner not installed")
        save_state("off")
        return None
    # rdio-scanner runs as a web service
    cmd = "rdio-scanner 2>/dev/null"
    proc = subprocess.Popen(cmd, shell=True, start_new_session=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    save_state("scanner", proc.pid)
    log.info("Scanner mode started (PID %d)", proc.pid)
    return proc

def stop_all():
    """Stop all SDR decoding."""
    state = get_state()
    kill_pid(state.get("pid"))
    kill_all_sdr_processes()
    save_state("off")
    log.info("All SDR modes stopped")

def set_mode(mode):
    """Switch to a new SDR mode."""
    # Stop current mode first
    stop_all()
    time.sleep(1)

    if mode == "off":
        # Turn off SDR module too
        if which("aiov2_ctl"):
            sh("sudo -n aiov2_ctl SDR off 2>/dev/null")
        return {"mode": "off", "ok": True}

    if mode == "pager":
        proc = start_pager()
    elif mode == "ais":
        proc = start_ais()
    elif mode == "dsc":
        proc = start_dsc()
    elif mode == "scanner":
        proc = start_scanner()
    else:
        return {"mode": "off", "ok": False, "error": f"Unknown mode: {mode}"}

    if proc is None:
        return {"mode": "off", "ok": False, "error": "Failed to start"}
    return {"mode": mode, "ok": True, "pid": proc.pid}

def get_status():
    """Get current mode status."""
    state = get_state()
    mode = state.get("mode", "off")
    pid = state.get("pid")
    alive = False
    if pid:
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
    return {
        "mode": mode,
        "pid": pid,
        "alive": alive,
        "frequency": FREQS.get(mode, None),
    }

def main():
    if len(sys.argv) < 2:
        print("Usage: sdr-mode <pager|ais|dsc|scanner|off|status>")
        sys.exit(1)

    mode = sys.argv[1].lower()

    if mode == "status":
        status = get_status()
        print(json.dumps(status, indent=2))
    elif mode in ("pager", "ais", "dsc", "scanner", "off"):
        result = set_mode(mode)
        print(json.dumps(result, indent=2))
        if not result.get("ok"):
            sys.exit(1)
    else:
        print(f"Unknown mode: {mode}")
        print("Usage: sdr-mode <pager|ais|dsc|scanner|off|status>")
        sys.exit(1)

if __name__ == "__main__":
    main()
