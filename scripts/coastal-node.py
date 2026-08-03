#!/usr/bin/env python3
"""
Coastal Node — standalone daemon for the uConsole as a portable CoastalHub receiver.

Runs as a systemd service.  Manages:
  - SDR mode switching (pager / AIS / DSC / scanner / off)
  - Decoding pager (POCSAG) and DSC messages via multimon-ng
  - Submitting decoded messages to CoastalHub (PagerMon API + DSC webhook)
  - GPS location updates (read GPS → reverse geocode → update node location)
  - Local alerting via Pushover, Meshtastic, or MeshCore when offline
  - Heartbeat to CoastalHub showing the node is alive

Configuration: /etc/coastalhub/node.conf
State: /run/coastal-node/state.json
Log: /var/log/coastal-node.log

CLI:
  coastal-node status        — current mode, GPS, last message
  coastal-node mode pager    — switch to pager decoding
  coastal-node mode ais      — switch to AIS tracking
  coastal-node mode dsc      — switch to DSC decoding
  coastal-node mode off      — stop SDR
  coastal-node gps           — show current GPS position and village
  coastal-node test pager    — send a test pager message to CoastalHub
  coastal-node test dsc      — send a test DSC event to CoastalHub
  coastal-node heartbeat     — send a heartbeat to CoastalHub
"""

from __future__ import annotations

import subprocess
import sys
import os
import time
import json
import signal
import logging
import threading
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIG_FILE = "/etc/coastalhub/node.conf"
STATE_DIR = "/run/coastal-node"
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOG_FILE = "/var/log/coastal-node.log"

# Fallback log location if /var/log not writable
try:
    open(LOG_FILE, "a").close()
except (PermissionError, OSError):
    LOG_FILE = os.path.expanduser("~/coastal-node.log")

FREQS = {
    "pager": 153.075,   # RNLI POCSAG
    "ais":  161.975,    # AIS 1 (also 162.025 for AIS 2)
    "dsc":  156.525,    # VHF Ch 70
}

# Reverse geocoding
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger("coastal-node")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def sh(cmd: str, timeout: int = 5) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""

def which(cmd: str) -> bool:
    return sh(f"command -v {cmd}") != ""

def load_config() -> dict:
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

def ensure_state_dir():
    os.makedirs(STATE_DIR, exist_ok=True)

def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"mode": "off", "gps": None, "village": None, "last_msg": None, "pid": None}

def save_state(state: dict):
    ensure_state_dir()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ---------------------------------------------------------------------------
# CoastalHub API
# ---------------------------------------------------------------------------
def submit_pagermon(address: str, message: str, source: str) -> bool:
    """Submit a pager message to PagerMon."""
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
            "User-Agent": "uConsole-CoastalNode/1.0",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        log.info("PagerMon OK: addr=%s msg=%s -> %d", address, message[:50], resp.status)
        return True
    except Exception as e:
        log.warning("PagerMon submit failed: %s", e)
        return False

def submit_dsc(payload: dict) -> bool:
    """Submit a DSC event to CoastalHub webhook."""
    cfg = load_config()
    url = cfg.get("COASTALHUB_URL", "https://coastalhub.uk") + "/api/dsc/webhook"
    token = cfg.get("COASTALHUB_DSC_TOKEN", "")
    data = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "uConsole-CoastalNode/1.0",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        log.info("DSC OK: %d", resp.status)
        return True
    except Exception as e:
        log.warning("DSC submit failed: %s", e)
        return False

def send_heartbeat():
    """Send a heartbeat to CoastalHub showing the node is alive."""
    cfg = load_config()
    url = cfg.get("COASTALHUB_URL", "https://coastalhub.uk") + "/api/dsc/heartbeats"
    token = cfg.get("COASTALHUB_DSC_TOKEN", "")
    state = load_state()
    payload = json.dumps({
        "nodeId": cfg.get("NODE_ID", "uconsole-portable-node"),
        "nodeName": cfg.get("NODE_NAME", "uConsole Portable"),
        "lat": state.get("gps", {}).get("lat") if state.get("gps") else None,
        "lon": state.get("gps", {}).get("lon") if state.get("gps") else None,
        "village": state.get("village"),
        "mode": state.get("mode", "off"),
        "timestamp": int(time.time()),
    }).encode()
    try:
        req = urllib.request.Request(url, data=payload, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "uConsole-CoastalNode/1.0",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        log.info("Heartbeat OK: %d", resp.status)
    except Exception as e:
        log.debug("Heartbeat failed: %s", e)

# ---------------------------------------------------------------------------
# GPS
# ---------------------------------------------------------------------------
def read_gps() -> dict | None:
    """Read GPS position from gpsd."""
    try:
        # Use gpspipe to get JSON from gpsd
        out = sh("gpspipe -w -n 1 2>/dev/null", timeout=3)
        for line in out.splitlines():
            if '"class":"TPV"' in line:
                d = json.loads(line)
                lat = d.get("lat")
                lon = d.get("lon")
                if lat is not None and lon is not None:
                    return {"lat": lat, "lon": lon}
    except Exception:
        pass
    # Fallback: read from /dev/ttyAMA0 directly via cgps
    try:
        out = sh("cgps -s 2>/dev/null", timeout=3)
        if "latitude" in out.lower():
            # Parse cgps output
            for line in out.splitlines():
                if "latitude" in line.lower():
                    log.debug("GPS via cgps: %s", line.strip())
    except Exception:
        pass
    return None

def reverse_geocode(lat: float, lon: float) -> str | None:
    """Reverse geocode GPS coordinates to nearest village name."""
    try:
        url = f"{NOMINATIM_URL}?format=json&lat={lat}&lon={lon}&zoom=14&addressdetails=1"
        req = urllib.request.Request(url, headers={"User-Agent": "uConsole-CoastalNode/1.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        # Try to get village/town/hamlet name
        addr = data.get("address", {})
        for key in ("village", "town", "hamlet", "suburb", "city_district", "city"):
            if addr.get(key):
                return addr[key]
        # Fallback to display_name first part
        if data.get("display_name"):
            return data["display_name"].split(",")[0]
    except Exception as e:
        log.debug("Reverse geocode failed: %s", e)
    return None

def update_gps_location():
    """Read GPS, reverse geocode, update node location, send heartbeat."""
    state = load_state()
    gps = read_gps()
    if not gps:
        log.debug("No GPS fix")
        return
    lat, lon = gps["lat"], gps["lon"]
    village = reverse_geocode(lat, lon)
    state["gps"] = gps
    state["village"] = village
    save_state(state)
    if village:
        log.info("GPS: %.5f, %.5f — %s", lat, lon, village)
    else:
        log.info("GPS: %.5f, %.5f", lat, lon)
    # Send heartbeat with location
    send_heartbeat()

# ---------------------------------------------------------------------------
# SDR control
# ---------------------------------------------------------------------------
def ensure_sdr_on():
    if which("aiov2_ctl"):
        sh("sudo -n aiov2_ctl SDR on 2>/dev/null")
        time.sleep(1)

def kill_pid(pid: int):
    if pid and pid > 0:
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        except ProcessLookupError:
            pass

def kill_sdr_processes():
    for proc in ["multimon-ng", "ais-catcher", "rtl_fm", "rtl_433"]:
        sh(f"pkill -f {proc} 2>/dev/null")
    time.sleep(0.5)

# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def parse_pager(proc, source_name):
    """Parse multimon-ng POCSAG output and submit to PagerMon."""
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
                    # Update state
                    state = load_state()
                    state["last_msg"] = {
                        "type": "pager",
                        "address": address,
                        "message": msg,
                        "time": int(time.time()),
                    }
                    save_state(state)
                    # Send local alert
                    send_local_alert(f"Pager: {msg}", "pager")
            except Exception as e:
                log.debug("Pager parse error: %s", e)

def parse_dsc(proc, source_name):
    """Parse multimon-ng DSC output and submit to CoastalHub."""
    for line in proc.stdout:
        line = line.decode("utf-8", errors="replace").strip()
        if "DSC" in line and len(line) > 10:
            try:
                # DSC messages from multimon-ng contain the decoded content
                log.info("DSC raw: %s", line[:80])
                payload = {
                    "type": "dsc",
                    "raw": line,
                    "source": source_name,
                    "timestamp": int(time.time()),
                }
                submit_dsc(payload)
                state = load_state()
                state["last_msg"] = {
                    "type": "dsc",
                    "raw": line[:100],
                    "time": int(time.time()),
                }
                save_state(state)
                send_local_alert(f"DSC: {line[:60]}", "dsc")
            except Exception as e:
                log.debug("DSC parse error: %s", e)

def parse_ais(proc, source_name):
    """Read AIS-catcher output."""
    for line in proc.stdout:
        line = line.decode("utf-8", errors="replace").strip()
        if line.startswith("{"):
            try:
                msg = json.loads(line)
                mmsi = msg.get("MMSI", "?")
                log.info("AIS: MMSI=%s type=%s", mmsi, msg.get("MsgType", "?"))
                state = load_state()
                state["last_msg"] = {
                    "type": "ais",
                    "mmsi": mmsi,
                    "time": int(time.time()),
                }
                save_state(state)
            except json.JSONDecodeError:
                pass

# ---------------------------------------------------------------------------
# Local alerts
# ---------------------------------------------------------------------------
def send_local_alert(message: str, alert_type: str):
    """Send a local alert via available channels."""
    # Try Pushover first (needs internet)
    cfg = load_config()
    pushover_token = cfg.get("PUSHOVER_TOKEN", "")
    pushover_user = cfg.get("PUSHOVER_USER", "")
    if pushover_token and pushover_user:
        try:
            data = urllib.parse.urlencode({
                "token": pushover_token,
                "user": pushover_user,
                "message": message,
                "title": f"Coastal Node — {alert_type.upper()}",
                "priority": "1" if alert_type == "dsc" else "0",
            }).encode()
            req = urllib.request.Request("https://api.pushover.net/1/messages.json",
                                         data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
            urllib.request.urlopen(req, timeout=10)
            log.info("Pushover alert sent: %s", message[:40])
            return
        except Exception as e:
            log.debug("Pushover failed: %s", e)

    # Try Meshtastic (if available and running)
    if which("meshtastic"):
        try:
            sh(f"meshtastic --sendtext '{message}' 2>/dev/null", timeout=5)
            log.info("Meshtastic alert sent")
            return
        except Exception:
            pass

    # Play a sound
    if which("aplay"):
        sh("aplay /usr/share/sounds/alsa/Front_Center.wav 2>/dev/null &", timeout=1)

# ---------------------------------------------------------------------------
# Mode management
# ---------------------------------------------------------------------------
_current_proc = None
_parser_thread = None

def set_mode(mode: str) -> dict:
    """Switch SDR to a new decode mode."""
    global _current_proc, _parser_thread
    # Stop current
    if _current_proc:
        kill_pid(_current_proc.pid)
    _current_proc = None
    kill_sdr_processes()
    time.sleep(1)

    state = load_state()

    if mode == "off":
        if which("aiov2_ctl"):
            sh("sudo -n aiov2_ctl SDR off 2>/dev/null")
        state["mode"] = "off"
        save_state(state)
        log.info("SDR off")
        return {"mode": "off", "ok": True}

    ensure_sdr_on()
    cfg = load_config()
    source = cfg.get("NODE_NAME", "uConsole")
    freq = FREQS.get(mode)
    if not freq:
        return {"mode": "off", "ok": False, "error": f"Unknown mode: {mode}"}

    if mode == "pager":
        cmd = (f"rtl_fm -f {freq}M -s 22050 -l 0 -g 40 -E DC 2>/dev/null | "
               f"multimon-ng -t raw -a POCSAG512 -a POCSAG1200 -a POCSAG2400 -f alpha - 2>/dev/null")
        parser = parse_pager
    elif mode == "dsc":
        cmd = (f"rtl_fm -f {freq}M -s 22050 -l 0 -g 40 -E DC 2>/dev/null | "
               f"multimon-ng -t raw -a DSC -f alpha - 2>/dev/null")
        parser = parse_dsc
    elif mode == "ais":
        if which("ais-catcher"):
            cmd = "ais-catcher -r 96000 -g 40 -s -j 2>/dev/null"
        elif which("rtl_ais"):
            cmd = "rtl_ais -n 2>/dev/null"
        else:
            state["mode"] = "off"
            save_state(state)
            return {"mode": "off", "ok": False, "error": "No AIS decoder installed"}
        parser = parse_ais
    elif mode == "scanner":
        # Scanner mode uses rdio-scanner (web service)
        if which("rdio-scanner"):
            cmd = "rdio-scanner 2>/dev/null"
            parser = None
        else:
            state["mode"] = "off"
            save_state(state)
            return {"mode": "off", "ok": False, "error": "rdio-scanner not installed"}
    else:
        return {"mode": "off", "ok": False, "error": f"Unknown mode: {mode}"}

    _current_proc = subprocess.Popen(cmd, shell=True, start_new_session=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if parser and _current_proc.stdout:
        _parser_thread = threading.Thread(target=parser, args=(_current_proc, source), daemon=True)
        _parser_thread.start()

    state["mode"] = mode
    state["pid"] = _current_proc.pid
    save_state(state)
    log.info("Mode: %s on %.3f MHz (PID %d)", mode, freq, _current_proc.pid)
    return {"mode": mode, "ok": True, "pid": _current_proc.pid}

# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------
def run_daemon():
    """Main daemon loop — manages SDR, GPS, heartbeats."""
    log.info("Coastal Node daemon starting")
    state = load_state()
    state["mode"] = "off"
    save_state(state)

    # Start in pager mode by default
    set_mode("pager")

    gps_timer = 0
    heartbeat_timer = 0
    GPS_INTERVAL = 300  # 5 minutes
    HEARTBEAT_INTERVAL = 60  # 1 minute

    while True:
        try:
            # GPS update
            if time.time() - gps_timer > GPS_INTERVAL:
                update_gps_location()
                gps_timer = time.time()

            # Heartbeat
            if time.time() - heartbeat_timer > HEARTBEAT_INTERVAL:
                send_heartbeat()
                heartbeat_timer = time.time()

            # Check if SDR process is alive
            state = load_state()
            if state.get("mode") != "off" and state.get("pid"):
                try:
                    os.kill(state["pid"], 0)
                except ProcessLookupError:
                    log.warning("SDR process died, restarting %s", state["mode"])
                    set_mode(state["mode"])

            time.sleep(10)
        except KeyboardInterrupt:
            log.info("Shutting down")
            set_mode("off")
            break
        except Exception as e:
            log.error("Daemon error: %s", e)
            time.sleep(30)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cmd_status():
    state = load_state()
    print(f"Mode:    {state.get('mode', 'off')}")
    print(f"PID:     {state.get('pid', 'none')}")
    gps = state.get("gps")
    if gps:
        print(f"GPS:     {gps['lat']:.5f}, {gps['lon']:.5f}")
        print(f"Village: {state.get('village', 'unknown')}")
    else:
        print("GPS:     no fix")
    last = state.get("last_msg")
    if last:
        ts = time.strftime("%H:%M:%S", time.localtime(last.get("time", 0)))
        print(f"Last:    [{ts}] {last.get('type', '?')}: {str(last.get('message', last.get('raw', last.get('mmsi', ''))))[:60]}")
    else:
        print("Last:    no messages")
    # Check if daemon is running
    daemon_pid = sh("pgrep -f 'coastal-node.*--daemon' 2>/dev/null")
    print(f"Daemon:  {'running' if daemon_pid else 'stopped'}")

def cmd_mode(mode: str):
    result = set_mode(mode)
    print(json.dumps(result, indent=2))

def cmd_gps():
    gps = read_gps()
    if gps:
        village = reverse_geocode(gps["lat"], gps["lon"])
        print(f"Lat:     {gps['lat']:.5f}")
        print(f"Lon:     {gps['lon']:.5f}")
        print(f"Village: {village or 'unknown'}")
    else:
        print("No GPS fix")

def cmd_test_pager():
    cfg = load_config()
    source = cfg.get("NODE_NAME", "uConsole")
    ok = submit_pagermon("0000000", "TEST from uConsole Coastal Node", source)
    print(f"PagerMon test: {'OK' if ok else 'FAILED'}")

def cmd_test_dsc():
    payload = {
        "type": "dsc",
        "raw": "TEST DSC from uConsole Coastal Node",
        "source": "uConsole",
        "timestamp": int(time.time()),
    }
    ok = submit_dsc(payload)
    print(f"DSC test: {'OK' if ok else 'FAILED'}")

def cmd_heartbeat():
    send_heartbeat()
    print("Heartbeat sent")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "status":
        cmd_status()
    elif cmd == "mode" and len(sys.argv) >= 3:
        cmd_mode(sys.argv[2].lower())
    elif cmd == "gps":
        cmd_gps()
    elif cmd == "test" and len(sys.argv) >= 3:
        if sys.argv[2] == "pager":
            cmd_test_pager()
        elif sys.argv[2] == "dsc":
            cmd_test_dsc()
        else:
            print(f"Unknown test: {sys.argv[2]}")
    elif cmd == "heartbeat":
        cmd_heartbeat()
    elif cmd == "--daemon":
        run_daemon()
    else:
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()
