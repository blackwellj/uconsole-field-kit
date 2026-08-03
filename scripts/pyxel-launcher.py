#!/usr/bin/env python3
"""
RF-Deck — a Pyxel-based cyberpunk launcher for the uConsole CM5.

640x360, 30 FPS, pixel-art HUD aesthetic.
Mouse + keyboard input. Black background, neon accents.
Replaces the PyQt6 Marine Console with something faster and cooler.

Controls:
  1-5     Switch pages (DASH/SDR/MESH/MARINE/SYS)
  TAB     Next page
  Arrows  Navigate buttons within page
  ENTER   Activate selected button
  ESC     Exit to desktop
  Click   Click any button directly
"""

import os
import subprocess
import sys
import time
import math
import random
from pathlib import Path
from collections import deque

import pyxel

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
W, H = 640, 360
FPS = 30

# Layout
TOP_H = 18          # top status bar
SIDE_W = 46         # left sidebar
BOT_H = 80          # bottom event log
CONTENT_X = SIDE_W
CONTENT_Y = TOP_H
CONTENT_W = W - SIDE_W
CONTENT_H = H - TOP_H - BOT_H
LOG_Y = H - BOT_H
LOG_H = BOT_H

# Pyxel 16-color palette indices
C_BG = 0          # black
C_DARK = 1       # dark blue/grey
C_PURPLE = 2     # magenta
C_CYAN = 3       # bright cyan
C_RED = 8        # red
C_ORANGE = 9     # orange
C_YELLOW = 10    # yellow
C_GREEN = 11     # bright green
C_WHITE = 7      # white
C_GREY = 13      # dim grey
C_BLUE = 12      # medium blue

# ---------------------------------------------------------------------------
# Shell helpers (same logic as field-launcher.py)
# ---------------------------------------------------------------------------
def sh(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""

def sudo_sh(cmd, timeout=5):
    return sh(f"sudo -n {cmd}", timeout=timeout)

def which(cmd):
    return sh(f"command -v {cmd}") != ""

def launch(cmd):
    subprocess.Popen(cmd, shell=True, start_new_session=True)

def launch_terminal(cmd=""):
    for term in ("xfce4-terminal", "x-terminal-emulator", "qterminal", "xterm"):
        if which(term):
            full = f"{term} -e bash -c '{cmd}; exec bash'" if cmd else term
            launch(full)
            return

def launch_browser(url):
    for browser in ("x-www-browser", "chromium", "firefox", "epiphany"):
        if which(browser):
            launch(f"{browser} {url}")
            return
    launch(f"xdg-open {url}")

# ---------------------------------------------------------------------------
# Status readers (reused from field-launcher.py)
# ---------------------------------------------------------------------------
def get_battery():
    info = {"capacity": "?", "power": "?", "charging": False}
    for supply in ("axp20x-battery", "axp22x-battery", "BAT0", "BAT1"):
        p = Path(f"/sys/class/power_supply/{supply}")
        if p.is_dir():
            cap = sh(f"cat {p}/capacity 2>/dev/null")
            vnow = sh(f"cat {p}/voltage_now 2>/dev/null")
            inow = sh(f"cat {p}/current_now 2>/dev/null")
            if cap:
                info["capacity"] = cap
            if vnow and inow:
                try:
                    v = int(vnow) / 1_000_000
                    ma = int(inow) / 1_000_000
                    info["power"] = f"{abs(ma * v):.1f}W"
                except ValueError:
                    pass
            break
    for s in ("axp22x-ac", "AC0", "ADP1"):
        p = Path(f"/sys/class/power_supply/{s}/online")
        if p.exists() and sh(f"cat {p}") == "1":
            info["charging"] = True
            break
    return info

def get_wifi():
    info = {"ssid": "—", "ip": "—"}
    ssid = sh("iwgetid -r 2>/dev/null") or sh("nmcli -t -f active,ssid dev wifi 2>/dev/null | grep '^yes' | cut -d: -f2")
    if ssid:
        info["ssid"] = ssid[:14]
    ip = sh("ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1")
    if ip:
        info["ip"] = ip
    return info

def get_aio_state():
    states = {}
    if which("aiov2_ctl"):
        out = sh("aiov2_ctl 2>/dev/null")
        for line in out.splitlines():
            if ":" in line:
                name, state = line.split(":", 1)
                states[name.strip().upper()] = state.strip().upper() == "ON"
    return states

def get_mesh_mode():
    for unit, label in [
        ("meshtasticd.service", "Meshtastic"),
        ("meshcore.service", "MeshCore"),
        ("meshcore-uconsole.service", "MeshCore"),
        ("meshcore-gui.service", "MeshCore"),
    ]:
        if sh(f"systemctl is-active {unit} 2>/dev/null") == "active":
            return label
    return "Off"

def get_sdr_mode():
    """Check what the SDR is currently decoding via iNTERCEPT or sdr-mode.py."""
    # Check sdr-mode.py state
    mode_file = Path("/tmp/sdr-mode-current")
    if mode_file.exists():
        mode = sh(f"cat {mode_file}")
        if mode:
            return mode.capitalize()
    # Check if iNTERCEPT is running
    if sh("systemctl is-active intercept 2>/dev/null") == "active" or sh("pgrep -f intercept 2>/dev/null"):
        return "iNTERCEPT"
    return "Off"

def get_kb_backlight():
    for path in ("/sys/class/leds/kbd_backlight/brightness",
                "/sys/class/leds/clockworkpi::kbd_backlight/brightness"):
        if Path(path).exists():
            return int(sh(f"cat {path}") or "0") > 0
    return False

def get_gps_status():
    return sh("systemctl is-active gpsd 2>/dev/null") == "active"

# ---------------------------------------------------------------------------
# Page definitions
# Pages are lists of buttons. Each button: (label, action_fn, color, row, col)
# ---------------------------------------------------------------------------
PAGE_NAMES = ["DASH", "SDR", "MESH", "MARINE", "SYS"]
PAGE_ICONS = ["◆", "📡", "🤖", "⚓", "⚙"]
# Simpler ASCII-safe icons for pixel font
PAGE_ICONS = ["DASH", "SDR", "MESH", "SEA", "SYS"]

# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------
class RFDeck:
    def __init__(self):
        pyxel.init(W, H, title="RF-Deck", fps=FPS,
                   quit_key=pyxel.KEY_NONE, display_scale=2)
        try:
            pyxel.fullscreen(True)
        except Exception:
            pass
        pyxel.mouse(True)

        # State
        self.page = 0  # 0=DASH, 1=SDR, 2=MESH, 3=MARINE, 4=SYS
        self.btn_selected = 0
        self.event_log = deque(maxlen=20)
        self.aio_states = {}
        self.battery = {"capacity": "?", "power": "?", "charging": False}
        self.wifi = {"ssid": "—", "ip": "—"}
        self.mesh_mode = "Off"
        self.sdr_mode = "Off"
        self.gps_on = False
        self.kb_backlight = False
        self.time_str = "--:--"

        # Button definitions per page — built dynamically
        self.page_buttons = []
        self._build_buttons()

        # Initial status fetch
        self._refresh_status()

        # Timers
        self._status_tick = 0
        self._aio_tick = 0
        self._scan_anim = 0

        self._log("SYS] RF-Deck online")
        self._log("SYS] Ready.")

        pyxel.run(self._update, self._draw)

    # ---- Button builder ----
    def _build_buttons(self):
        """Build button lists for each page. Each: (label, fn, color, x, y, w, h)."""
        bx = CONTENT_X + 8
        bw = CONTENT_W - 16
        by = CONTENT_Y + 8

        # Page 0: DASH — quick overview + quick launch
        dash = []
        apps = [
            ("iNTERCEPT", self._act_intercept, C_CYAN),
            ("SDR++", self._act_sdrpp, C_CYAN),
            ("WSJT-X", self._act_wsjtx, C_YELLOW),
            ("Terminal", self._act_terminal, C_WHITE),
            ("GPS Client", self._act_gpsclient, C_GREEN),
            ("AIO Tray", self._act_aiotray, C_CYAN),
        ]
        for i, (label, fn, color) in enumerate(apps):
            row, col = i // 2, i % 2
            w = (bw - 8) // 2
            x = bx + col * (w + 8)
            y = by + 24 + row * 34
            dash.append((label, fn, color, x, y, w, 28))
        self.page_buttons.append(dash)

        # Page 1: SDR
        sdr = []
        sdr_apps = [
            ("iNTERCEPT", self._act_intercept, C_CYAN),
            ("iNTERCEPT Web", self._act_intercept_web, C_CYAN),
            ("SDR++", self._act_sdrpp, C_CYAN),
            ("tar1090 ADS-B", self._act_tar1090, C_GREEN),
            ("WSJT-X FT8", self._act_wsjtx, C_YELLOW),
            ("rtl_433 Scan", self._act_rtl433, C_ORANGE),
        ]
        for i, (label, fn, color) in enumerate(sdr_apps):
            row, col = i // 2, i % 2
            w = (bw - 8) // 2
            x = bx + col * (w + 8)
            y = by + 24 + row * 34
            sdr.append((label, fn, color, x, y, w, 28))
        self.page_buttons.append(sdr)

        # Page 2: MESH
        mesh = []
        mesh_apps = [
            ("Meshtastic", self._act_mesh_mh, C_GREEN),
            ("MeshCore", self._act_mesh_mc, C_PURPLE),
            ("Mesh Off", self._act_mesh_off, C_RED),
            ("Contact TUI", self._act_contact, C_GREEN),
            ("MeshCore TUI", self._act_mctui, C_PURPLE),
            ("MeshDash Web", self._act_meshdash, C_CYAN),
        ]
        for i, (label, fn, color) in enumerate(mesh_apps):
            row, col = i // 2, i % 2
            w = (bw - 8) // 2
            x = bx + col * (w + 8)
            y = by + 24 + row * 34
            mesh.append((label, fn, color, x, y, w, 28))
        self.page_buttons.append(mesh)

        # Page 3: MARINE
        marine = []
        marine_apps = [
            ("iNTERCEPT AIS", self._act_intercept, C_CYAN),
            ("iNTERCEPT Web", self._act_intercept_web, C_CYAN),
            ("VHF Ref", self._act_noop, C_GREEN),
            ("DSC Monitor", self._act_intercept_web, C_ORANGE),
        ]
        for i, (label, fn, color) in enumerate(marine_apps):
            row, col = i // 2, i % 2
            w = (bw - 8) // 2
            x = bx + col * (w + 8)
            y = by + 24 + row * 34
            marine.append((label, fn, color, x, y, w, 28))
        self.page_buttons.append(marine)

        # Page 4: SYS
        sysp = []
        sys_apps = [
            ("GPS Toggle", self._act_gps_toggle, C_GREEN),
            ("KB Backlight", self._act_kbd, C_YELLOW),
            ("Diagnostics", self._act_diag, C_ORANGE),
            ("Terminal", self._act_terminal, C_WHITE),
            ("Reboot", self._act_reboot, C_ORANGE),
            ("Shutdown", self._act_shutdown, C_RED),
        ]
        for i, (label, fn, color) in enumerate(sys_apps):
            row, col = i // 2, i % 2
            w = (bw - 8) // 2
            x = bx + col * (w + 8)
            y = by + 24 + row * 34
            sysp.append((label, fn, color, x, y, w, 28))
        self.page_buttons.append(sysp)

    # ---- Actions ----
    def _log(self, msg):
        self.event_log.appendleft(f"{time.strftime('%H:%M:%S')} {msg}")

    def _act_noop(self):
        self._log("NOP] Not implemented yet")

    def _act_intercept(self):
        if Path("/opt/intercept/start.sh").exists():
            launch("cd /opt/intercept && sudo ./start.sh")
            time.sleep(2)
            launch_browser("http://localhost:5050")
            self._log("SDR] iNTERCEPT started + web launched")
        else:
            self._log("ERR] iNTERCEPT not installed")

    def _act_intercept_web(self):
        launch_browser("http://localhost:5050")
        self._log("WEB] iNTERCEPT http://localhost:5050")

    def _act_sdrpp(self):
        if which("sdrpp-brown"):
            launch("sdrpp-brown &")
            self._log("SDR] SDR++ launched")
        elif which("sdrpp"):
            launch("sdrpp &")
            self._log("SDR] SDR++ launched")
        else:
            self._log("ERR] SDR++ not installed")

    def _act_tar1090(self):
        if sh("systemctl is-active readsb 2>/dev/null") != "active":
            sudo_sh("systemctl start readsb 2>/dev/null")
        launch_browser("http://localhost/tar1090")
        self._log("SDR] tar1090 ADS-B opened")

    def _act_wsjtx(self):
        if which("wsjtx"):
            launch("wsjtx &")
            self._log("HAM] WSJT-X launched")
        else:
            self._log("ERR] WSJT-X not installed")

    def _act_rtl433(self):
        launch_terminal("rtl_433 -G 2>&1 | head -100")
        self._log("SDR] rtl_433 scanning...")

    def _act_terminal(self):
        launch_terminal()
        self._log("SYS] Terminal opened")

    def _act_gpsclient(self):
        launch("pygpsclient 2>/dev/null &")
        self._log("GPS] PyGPSClient launched")

    def _act_aiotray(self):
        launch("aiov2_ctl --gui 2>/dev/null &")
        self._log("AIO] Tray GUI launched")

    def _act_mesh_mh(self):
        launch("sudo uconsole-radio meshtastic")
        self._log("MESH] Switching to Meshtastic...")

    def _act_mesh_mc(self):
        launch("sudo uconsole-radio meshcore")
        self._log("MESH] Switching to MeshCore...")

    def _act_mesh_off(self):
        launch("sudo uconsole-radio off")
        self._log("MESH] Mesh radio off")

    def _act_contact(self):
        if which("contact"):
            launch_terminal("contact --port /dev/ttyUSB0")
        else:
            launch_terminal("pipx install contact && contact --port /dev/ttyUSB0")
        self._log("MESH] Contact TUI")

    def _act_mctui(self):
        if which("tui-meshcore"):
            launch_terminal("tui-meshcore")
        else:
            launch_terminal("pipx install git+https://github.com/guax/tui-meshcore.git && tui-meshcore")
        self._log("MESH] MeshCore TUI")

    def _act_meshdash(self):
        launch_browser("http://localhost:8000")
        self._log("MESH] MeshDash http://localhost:8000")

    def _act_gps_toggle(self):
        self._toggle_aio("GPS")

    def _act_kbd(self):
        for path in ("/sys/class/leds/kbd_backlight/brightness",
                     "/sys/class/leds/clockworkpi::kbd_backlight/brightness"):
            if Path(path).exists():
                current = int(sh(f"cat {path}") or "0")
                maxb = int(sh(f"cat {path.replace('brightness', 'max_brightness')}") or "1")
                new = "0" if current > 0 else str(maxb)
                sudo_sh(f"sh -c 'echo {new} > {path}'")
                self._log(f"KBD] Backlight {'ON' if new != '0' else 'OFF'}")
                return

    def _act_diag(self):
        launch_terminal("uconsole-doctor")
        self._log("SYS] Running diagnostics...")

    def _act_reboot(self):
        self._log("SYS] Rebooting...")
        subprocess.run("sudo reboot", shell=True)

    def _act_shutdown(self):
        self._log("SYS] Shutting down...")
        subprocess.run("sudo shutdown -h now", shell=True)

    def _toggle_aio(self, name):
        current = self.aio_states.get(name, False)
        action = "off" if current else "on"
        if which("aiov2_ctl"):
            sudo_sh(f"aiov2_ctl {name} {action}")
            self._log(f"AIO] {name} {action.upper()}")
        elif which("pinctrl"):
            pin_map = {"GPS": 27, "LORA": 16, "SDR": 7, "USB": 23}
            pin = pin_map.get(name)
            if pin:
                sudo_sh(f"pinctrl set {pin} op {'dh' if action == 'on' else 'dl'}")
                self._log(f"AIO] {name} {action.upper()}")
        time.sleep(0.3)
        self._refresh_aio()

    # ---- Status refresh ----
    def _refresh_status(self):
        self.battery = get_battery()
        self.wifi = get_wifi()
        self.mesh_mode = get_mesh_mode()
        self.sdr_mode = get_sdr_mode()
        self.gps_on = get_gps_status()
        self.kb_backlight = get_kb_backlight()
        self.time_str = time.strftime("%H:%M")

    def _refresh_aio(self):
        self.aio_states = get_aio_state()

    # ---- Update loop ----
    def _update(self):
        # Page switching — keyboard
        for i in range(5):
            if pyxel.btnp(pyxel.KEY_1 + i):
                self._switch_page(i)
                return
        if pyxel.btnp(pyxel.KEY_TAB):
            self._switch_page((self.page + 1) % 5)
            return

        # Button navigation — keyboard
        if self.page_buttons[self.page]:
            n = len(self.page_buttons[self.page])
            if pyxel.btnp(pyxel.KEY_DOWN) or pyxel.btnp(pyxel.KEY_RIGHT):
                self.btn_selected = (self.btn_selected + 1) % n
            if pyxel.btnp(pyxel.KEY_UP) or pyxel.btnp(pyxel.KEY_LEFT):
                self.btn_selected = (self.btn_selected - 1) % n
            if pyxel.btnp(pyxel.KEY_RETURN):
                btn = self.page_buttons[self.page][self.btn_selected]
                btn[1]()  # call action fn

        # Mouse click — check all buttons on current page
        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            mx, my = pyxel.mouse_x, pyxel.mouse_y
            for i, (label, fn, color, x, y, w, h) in enumerate(self.page_buttons[self.page]):
                if x <= mx <= x + w and y <= my <= y + h:
                    self.btn_selected = i
                    fn()
                    return

        # Exit
        if pyxel.btnp(pyxel.KEY_ESCAPE):
            pyxel.quit()

        # Status refresh timers
        self._status_tick += 1
        if self._status_tick >= 90:  # ~3s at 30fps
            self._status_tick = 0
            self._refresh_status()

        self._aio_tick += 1
        if self._aio_tick >= 120:  # ~4s
            self._aio_tick = 0
            self._refresh_aio()

        # Scan animation
        self._scan_anim = (self._scan_anim + 1) % 120

    def _switch_page(self, idx):
        self.page = idx
        self.btn_selected = 0

    # ---- Draw ----
    def _draw(self):
        pyxel.cls(C_BG)

        self._draw_top_bar()
        self._draw_sidebar()
        self._draw_content()
        self._draw_log()

    def _draw_top_bar(self):
        # Background strip
        pyxel.rect(0, 0, W, TOP_H, C_DARK)
        pyxel.line(0, TOP_H, W, TOP_H, C_CYAN)

        # Title
        pyxel.text(4, 5, "RF-DECK", C_CYAN)

        # Status indicators
        x = 70
        # Battery
        bat = self.battery
        bc = C_GREEN if bat["capacity"] != "?" and int(bat["capacity"]) > 30 else C_RED
        if bat["charging"]:
            bc = C_CYAN
        bat_txt = f"BAT {bat['capacity']}%"
        if bat["charging"]:
            bat_txt = f"⚡{bat_txt}"
        self._draw_pill(x, 4, bat_txt, bc)
        x += len(bat_txt) * 4 + 16

        # Power
        if bat["power"] != "?":
            self._draw_pill(x, 4, f"PWR {bat['power']}", C_ORANGE)
            x += len(f"PWR {bat['power']}") * 4 + 16

        # GPS
        gc = C_GREEN if self.gps_on else C_RED
        self._draw_pill(x, 4, f"GPS {'ON' if self.gps_on else 'OFF'}", gc)
        x += 42

        # SDR mode
        sc = C_CYAN if self.sdr_mode != "Off" else C_GREY
        self._draw_pill(x, 4, f"SDR {self.sdr_mode[:8]}", sc)
        x += 60

        # Mesh
        mc = C_GREEN if self.mesh_mode == "Meshtastic" else C_PURPLE if self.mesh_mode == "MeshCore" else C_RED
        self._draw_pill(x, 4, f"MESH {self.mesh_mode[:6]}", mc)
        x += 60

        # WiFi (right-aligned)
        wifi_txt = f"WiFi {self.wifi['ssid']}"
        wx = W - len(wifi_txt) * 4 - 16 - 50
        self._draw_pill(wx, 4, wifi_txt, C_CYAN)

        # Clock (far right)
        clock_txt = self.time_str
        cx = W - len(clock_txt) * 4 - 8
        pyxel.text(cx, 5, clock_txt, C_WHITE)

    def _draw_pill(self, x, y, text, color):
        w = len(text) * 4 + 8
        pyxel.rectb(x, y, w, 11, color)
        pyxel.text(x + 4, y + 2, text, color)

    def _draw_sidebar(self):
        # Background
        pyxel.rect(0, TOP_H, SIDE_W, H - TOP_H, C_DARK)
        pyxel.line(SIDE_W, TOP_H, SIDE_W, H, C_CYAN)

        # Page icons
        for i, name in enumerate(PAGE_NAMES):
            y = TOP_H + 12 + i * 52
            # Icon box
            is_sel = (i == self.page)
            bg = C_DARK
            border = C_CYAN if is_sel else C_GREY
            text_col = C_CYAN if is_sel else C_GREY

            if is_sel:
                pyxel.rect(2, y, SIDE_W - 4, 44, C_BG)
                pyxel.rectb(2, y, SIDE_W - 4, 44, C_CYAN)
            else:
                pyxel.rectb(2, y, SIDE_W - 4, 44, C_GREY)

            # Page number
            num_col = C_CYAN if is_sel else C_GREY
            pyxel.text(6, y + 4, str(i + 1), num_col)

            # Icon text (short)
            icon = PAGE_ICONS[i]
            ix = (SIDE_W - len(icon) * 4) // 2
            pyxel.text(ix, y + 14, icon, text_col)

            # Selection indicator
            if is_sel:
                pyxel.text(6, y + 34, ">", C_CYAN)

        # Exit at bottom
        y = H - 44
        pyxel.rectb(2, y, SIDE_W - 4, 40, C_RED)
        pyxel.text(10, y + 8, "ESC", C_RED)
        pyxel.text(6, y + 20, "EXIT", C_RED)

    def _draw_content(self):
        # Background
        pyxel.rect(CONTENT_X, CONTENT_Y, CONTENT_W, CONTENT_H, C_BG)

        # Page header
        page_name = PAGE_NAMES[self.page]
        pyxel.text(CONTENT_X + 8, CONTENT_Y + 4, f"[{page_name}]", C_CYAN)
        # Underline
        pyxel.line(CONTENT_X + 8, CONTENT_Y + 14, CONTENT_X + CONTENT_W - 8, CONTENT_Y + 14, C_DARK)

        # Draw buttons
        for i, (label, fn, color, x, y, w, h) in enumerate(self.page_buttons[self.page]):
            is_sel = (i == self.btn_selected)
            self._draw_button(x, y, w, h, label, color, is_sel)

        # Page-specific extra info
        if self.page == 0:  # DASH
            self._draw_dash_info()
        elif self.page == 1:  # SDR
            self._draw_sdr_info()
        elif self.page == 2:  # MESH
            self._draw_mesh_info()
        elif self.page == 3:  # MARINE
            self._draw_marine_info()
        elif self.page == 4:  # SYS
            self._draw_sys_info()

    def _draw_button(self, x, y, w, h, label, color, selected):
        if selected:
            # Filled with color
            pyxel.rect(x, y, w, h, color)
            pyxel.rectb(x, y, w, h, C_WHITE)
            pyxel.text(x + 6, y + (h - 6) // 2, label, C_BG)
        else:
            pyxel.rect(x, y, w, h, C_BG)
            pyxel.rectb(x, y, w, h, color)
            pyxel.text(x + 6, y + (h - 6) // 2, label, color)

    def _draw_dash_info(self):
        """AIO module states + system summary on dash page."""
        x = CONTENT_X + 8
        y = CONTENT_Y + CONTENT_H - 70

        # AIO module toggles status
        pyxel.text(x, y, "AIO MODULES", C_CYAN)
        pyxel.line(x, y + 8, x + 200, y + 8, C_DARK)

        modules = ["GPS", "SDR", "USB", "LORA"]
        for i, name in enumerate(modules):
            on = self.aio_states.get(name, False)
            col = C_GREEN if on else C_RED
            icon = "●" if on else "○"
            mx = x + i * 52
            pyxel.text(mx, y + 14, f"{icon} {name}", col)

        # Quick stats
        pyxel.text(x + 230, y, "SYSTEM", C_CYAN)
        pyxel.line(x + 230, y + 8, x + 430, y + 8, C_DARK)
        stats = [
            f"Mesh: {self.mesh_mode}",
            f"SDR:  {self.sdr_mode}",
            f"GPS:  {'ON' if self.gps_on else 'OFF'}",
            f"WiFi: {self.wifi['ssid']}",
        ]
        for i, s in enumerate(stats):
            pyxel.text(x + 230, y + 14 + i * 10, s, C_WHITE)

        # Scan animation (radar sweep)
        cx = x + CONTENT_W - 60
        cy = y + 30
        r = 22
        pyxel.circb(cx, cy, r, C_DARK)
        pyxel.circb(cx, cy, r // 2, C_DARK)
        # Sweep line
        angle = self._scan_anim * 0.05
        ex = cx + int(math.cos(angle) * r)
        ey = cy + int(math.sin(angle) * r)
        pyxel.line(cx, cy, ex, ey, C_CYAN)
        # Center dot
        pyxel.pset(cx, cy, C_CYAN)

    def _draw_sdr_info(self):
        x = CONTENT_X + 8
        y = CONTENT_Y + CONTENT_H - 50
        pyxel.text(x, y, "SDR MODE: ", C_CYAN)
        mode_col = C_GREEN if self.sdr_mode != "Off" else C_GREY
        pyxel.text(x + 54, y, self.sdr_mode, mode_col)
        pyxel.text(x, y + 12, "One RTL-SDR = one decode at a time", C_GREY)
        pyxel.text(x, y + 22, "Use iNTERCEPT web UI to switch modes", C_GREY)

    def _draw_mesh_info(self):
        x = CONTENT_X + 8
        y = CONTENT_Y + CONTENT_H - 50
        pyxel.text(x, y, "MESH MODE: ", C_CYAN)
        mc = C_GREEN if self.mesh_mode == "Meshtastic" else C_PURPLE if self.mesh_mode == "MeshCore" else C_RED
        pyxel.text(x + 66, y, self.mesh_mode, mc)
        pyxel.text(x, y + 12, "Meshtastic and MeshCore share one SX1262", C_GREY)
        pyxel.text(x, y + 22, "Switching stops the inactive stack first", C_GREY)

    def _draw_marine_info(self):
        x = CONTENT_X + 8
        y = CONTENT_Y + CONTENT_H - 60
        pyxel.text(x, y, "VHF REFERENCE", C_CYAN)
        pyxel.line(x, y + 8, x + 200, y + 8, C_DARK)
        channels = [
            "Ch16 156.800 Distress",
            "Ch70 156.525 DSC",
            "Ch13 156.650 Bridge",
            "Ch87B 161.975 AIS1",
            "Ch88B 162.025 AIS2",
        ]
        for i, ch in enumerate(channels):
            pyxel.text(x, y + 14 + i * 10, ch, C_WHITE)

    def _draw_sys_info(self):
        x = CONTENT_X + 8
        y = CONTENT_Y + CONTENT_H - 50
        pyxel.text(x, y, "KBD BACKLIGHT: ", C_CYAN)
        bc = C_YELLOW if self.kb_backlight else C_RED
        pyxel.text(x + 90, y, "ON" if self.kb_backlight else "OFF", bc)
        pyxel.text(x, y + 12, "GPS: ", C_CYAN)
        gc = C_GREEN if self.gps_on else C_RED
        pyxel.text(x + 30, y + 12, "ON" if self.gps_on else "OFF", gc)

    def _draw_log(self):
        # Background
        pyxel.rect(0, LOG_Y, W, LOG_H, C_BG)
        pyxel.line(0, LOG_Y, W, LOG_Y, C_DARK)

        # Header
        pyxel.text(4, LOG_Y + 2, "> LOG", C_CYAN)
        pyxel.line(34, LOG_Y + 4, 60, LOG_Y + 4, C_CYAN)

        # Log lines
        max_lines = (LOG_H - 12) // 8
        for i, line in enumerate(list(self.event_log)[:max_lines]):
            color = C_WHITE
            if "ERR]" in line:
                color = C_RED
            elif "OK]" in line or "ON]" in line:
                color = C_GREEN
            elif "SDR]" in line:
                color = C_CYAN
            elif "MESH]" in line:
                color = C_PURPLE
            elif "AIO]" in line:
                color = C_YELLOW
            elif "SYS]" in line:
                color = C_GREY
            pyxel.text(8, LOG_Y + 12 + i * 9, line[:74], color)


def main():
    RFDeck()


if __name__ == "__main__":
    main()
