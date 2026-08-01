#!/usr/bin/env python3
"""
uConsole Marine Console — modern dark dashboard for the uConsole CM5.

Sidebar navigation, card-based layout, real-time status bar.
Designed for 1280x720.  Borderless, dark navy theme.
"""

from __future__ import annotations
import os, subprocess, sys, time
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QFont, QColor, QPalette, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QLabel, QFrame, QSizePolicy,
    QStackedWidget, QScrollArea, QSpacerItem,
)

# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------
def sh(cmd: str, timeout: int = 5) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""

def sudo_sh(cmd: str, timeout: int = 5) -> str:
    return sh(f"sudo -n {cmd}", timeout=timeout)

def which(cmd: str) -> bool:
    return sh(f"command -v {cmd}") != ""

def launch(cmd: str) -> None:
    subprocess.Popen(cmd, shell=True, start_new_session=True)

def launch_terminal(cmd: str = "") -> None:
    for term in ("xfce4-terminal", "x-terminal-emulator", "qterminal", "xterm"):
        if which(term):
            if cmd:
                full = f"{term} -e bash -c '{cmd}; exec bash'"
            else:
                full = term
            launch(full)
            return

def launch_browser(url: str) -> None:
    for browser in ("x-www-browser", "chromium", "firefox", "epiphany"):
        if which(browser):
            launch(f"{browser} {url}")
            return
    launch(f"xdg-open {url}")

# ---------------------------------------------------------------------------
# Status readers
# ---------------------------------------------------------------------------
def get_battery() -> dict:
    info = {"capacity": "?", "power": "?"}
    for supply in ("axp20x-battery", "axp22x-battery", "BAT0", "BAT1"):
        p = Path(f"/sys/class/power_supply/{supply}")
        if p.is_dir():
            cap = sh(f"cat {p}/capacity 2>/dev/null")
            vnow = sh(f"cat {p}/voltage_now 2>/dev/null")
            inow = sh(f"cat {p}/current_now 2>/dev/null")
            if cap: info["capacity"] = cap
            if vnow and inow:
                try:
                    v = int(vnow) / 1_000_000
                    ma = int(inow) / 1_000_000
                    info["power"] = f"{abs(ma * v):.1f}W"
                except ValueError: pass
            break
    return info

def get_ac() -> bool:
    for s in ("axp22x-ac", "AC0", "ADP1"):
        p = Path(f"/sys/class/power_supply/{s}/online")
        if p.exists():
            return sh(f"cat {p}") == "1"
    return False

def get_wifi() -> dict:
    info = {"ssid": "—", "ip": "—"}
    ssid = sh("iwgetid -r 2>/dev/null") or sh("nmcli -t -f active,ssid dev wifi 2>/dev/null | grep '^yes' | cut -d: -f2")
    if ssid: info["ssid"] = ssid[:14]
    ip = sh("ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1")
    if ip: info["ip"] = ip
    return info

def get_aio_state() -> dict:
    states = {}
    if which("aiov2_ctl"):
        out = sh("aiov2_ctl 2>/dev/null")
        for line in out.splitlines():
            if ":" in line:
                name, state = line.split(":", 1)
                states[name.strip().upper()] = state.strip().upper() == "ON"
    return states

def get_mesh_mode() -> str:
    for unit, label in [
        ("meshtasticd.service", "Meshtastic"),
        ("meshcore.service", "MeshCore"),
        ("meshcore-uconsole.service", "MeshCore"),
        ("meshcore-gui.service", "MeshCore"),
    ]:
        if sh(f"systemctl is-active {unit} 2>/dev/null") == "active":
            return label
    return "Off"

def get_kb_backlight() -> bool:
    for path in ("/sys/class/leds/kbd_backlight/brightness",
                "/sys/class/leds/clockworkpi::kbd_backlight/brightness"):
        if Path(path).exists():
            return int(sh(f"cat {path}") or "0") > 0
    return False

def get_vnc_status() -> str:
    return "ON" if sh("systemctl is-active x11vnc 2>/dev/null") == "active" else "OFF"

def get_gps_fix() -> str:
    """Try to get a GPS fix string from gpsd."""
    out = sh("cgps -s 2>/dev/null | head -5", timeout=3)
    if out:
        for line in out.splitlines():
            if "latitude" in line.lower() or "lat" in line.lower():
                return line.strip()
    # Fallback: check if gpsd has a fix
    if sh("systemctl is-active gpsd 2>/dev/null") == "active":
        return "GPSd active"
    return "No fix"

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
BG       = "#0a0e1a"
SIDEBAR  = "#0d1320"
PANEL    = "#141b2e"
CARD     = "#1a2238"
BORDER   = "#2a3550"
CYAN     = "#00b0d0"
GREEN    = "#00c070"
RED      = "#e03050"
ORANGE   = "#e08020"
PURPLE   = "#9040d0"
YELLOW   = "#d0b000"
WHITE    = "#c8d0e0"
DIM      = "#506070"
FONT     = "DejaVu Sans"
MONO     = "DejaVu Sans Mono"

# ---------------------------------------------------------------------------
# UI builders
# ---------------------------------------------------------------------------

def card_frame(title: str = "", color: str = CYAN) -> tuple[QFrame, QVBoxLayout]:
    """Create a card with a title bar. Returns (frame, content_layout)."""
    frame = QFrame()
    frame.setStyleSheet(f"""
        QFrame {{
            background-color: {CARD};
            border: 1px solid {BORDER};
            border-radius: 8px;
        }}
    """)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(10, 8, 10, 8)
    lay.setSpacing(4)

    if title:
        lbl = QLabel(title.upper())
        lbl.setFont(QFont(FONT, 8, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {color}; letter-spacing: 1px; padding-bottom: 4px; border: none;")
        lay.addWidget(lbl)
        # Separator line
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {BORDER}; border: none;")
        lay.addWidget(line)

    return frame, lay

def status_pill(text: str, color: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont(FONT, 8, QFont.Weight.Bold))
    lbl.setStyleSheet(f"""
        QLabel {{
            background-color: {color}18; color: {color};
            border: 1px solid {color}50; border-radius: 10px;
            padding: 2px 8px; border: none;
        }}
    """)
    return lbl

def action_btn(text: str, color: str = CYAN, h: int = 42, fs: int = 10) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(h)
    btn.setFont(QFont(FONT, fs, QFont.Weight.Bold))
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {PANEL}; color: {color};
            border: 1px solid {color}50; border-radius: 6px;
            padding: 4px 10px;
        }}
        QPushButton:hover {{
            background-color: {color}20; border: 1px solid {color};
        }}
        QPushButton:pressed {{
            background-color: {color}; color: {BG};
        }}
    """)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return btn

def toggle_btn(name: str, is_on: bool, h: int = 44) -> QPushButton:
    c = GREEN if is_on else RED
    btn = QPushButton(f"{name}  {'●' if is_on else '○'}")
    btn.setFixedHeight(h)
    btn.setFont(QFont(FONT, 9, QFont.Weight.Bold))
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {c}18; color: {c};
            border: 1px solid {c}80; border-radius: 6px;
        }}
        QPushButton:hover {{ background-color: {c}30; }}
        QPushButton:pressed {{ background-color: {c}; color: {BG}; }}
    """)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return btn

def sidebar_btn(text: str, color: str = WHITE) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedSize(56, 56)
    btn.setFont(QFont(FONT, 16, QFont.Weight.Bold))
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: transparent; color: {DIM};
            border: none; border-radius: 12px;
            text-align: center;
        }}
        QPushButton:hover {{
            background-color: {CYAN}15; color: {WHITE};
        }}
        QPushButton:checked {{
            background-color: {CYAN}25; color: {CYAN};
            border: 1px solid {CYAN}80;
        }}
    """)
    btn.setCheckable(True)
    return btn

def data_label(text: str, color: str = WHITE, mono: bool = False, size: int = 9) -> QLabel:
    lbl = QLabel(text)
    f = MONO if mono else FONT
    lbl.setFont(QFont(f, size))
    lbl.setStyleSheet(f"color: {color}; border: none;")
    lbl.setWordWrap(True)
    return lbl

# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MarineConsole(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("uConsole Marine Console")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.resize(1280, 720)
        self.aio_states = {}
        self._building = False

        self._build_ui()
        self._start_timers()

    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet(f"background-color: {BG};")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        root.addLayout(self._build_sidebar())

        # Right side: status bar + stacked content
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addLayout(self._build_status_bar())

        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background-color: {BG};")
        self.stack.addWidget(self._page_dashboard())
        self.stack.addWidget(self._page_marine())
        self.stack.addWidget(self._page_radio())
        self.stack.addWidget(self._page_mesh())
        self.stack.addWidget(self._page_system())
        right.addWidget(self.stack, 1)

        root.addLayout(right, 1)

    # ---- Sidebar ----
    def _build_sidebar(self) -> QVBoxLayout:
        bar = QVBoxLayout()
        bar.setContentsMargins(8, 10, 8, 10)
        bar.setSpacing(6)
        bar.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Logo
        logo = QLabel("◆")
        logo.setFixedHeight(48)
        logo.setFont(QFont(FONT, 18, QFont.Weight.Black))
        logo.setStyleSheet(f"color: {CYAN}; border: none; padding-left: 16px;")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(logo)

        # Nav buttons
        self.nav_buttons = {}
        pages = [
            ("dashboard", "🏠", "Dashboard"),
            ("marine", "⚓", "Marine"),
            ("radio", "📡", "Radio/SDR"),
            ("mesh", "📻", "Mesh"),
            ("system", "⚙", "System"),
        ]
        for key, icon, label in pages:
            btn = sidebar_btn(icon)
            btn.setToolTip(label)
            btn.clicked.connect(lambda _, k=key: self._switch_page(k))
            bar.addWidget(btn)
            self.nav_buttons[key] = btn
            # Small label
            lbl = QLabel(label)
            lbl.setFixedHeight(14)
            lbl.setFont(QFont(FONT, 6))
            lbl.setStyleSheet(f"color: {DIM}; border: none;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bar.addWidget(lbl)

        bar.addStretch()

        # Exit button at bottom
        btn_exit = QPushButton("✕")
        btn_exit.setFixedSize(56, 56)
        btn_exit.setFont(QFont(FONT, 16, QFont.Weight.Bold))
        btn_exit.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; color: {RED}80;
                border: none; border-radius: 12px;
            }}
            QPushButton:hover {{ background-color: {RED}20; color: {RED}; }}
        """)
        btn_exit.setToolTip("Exit to Desktop")
        btn_exit.clicked.connect(self.close)
        bar.addWidget(btn_exit)
        lbl_exit = QLabel("Exit")
        lbl_exit.setFixedHeight(14)
        lbl_exit.setFont(QFont(FONT, 6))
        lbl_exit.setStyleSheet(f"color: {DIM}; border: none;")
        lbl_exit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(lbl_exit)

        # Wrap in frame
        wrap = QFrame()
        wrap.setStyleSheet(f"background-color: {SIDEBAR}; border-right: 1px solid {BORDER};")
        wrap.setLayout(bar)
        wrap.setFixedWidth(76)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(wrap)
        return outer

    def _switch_page(self, key: str) -> None:
        self.stack.setCurrentIndex(["dashboard", "marine", "radio", "mesh", "system"].index(key))
        for k, btn in self.nav_buttons.items():
            btn.setChecked(k == key)

    # ---- Status bar ----
    def _build_status_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 6, 12, 6)
        bar.setSpacing(8)

        title = QLabel("MARINE CONSOLE")
        title.setFont(QFont(FONT, 9, QFont.Weight.Black))
        title.setStyleSheet(f"color: {CYAN}; letter-spacing: 2px; border: none;")
        bar.addWidget(title)

        bar.addStretch()

        self.lbl_bat = status_pill("BAT ?%", GREEN)
        self.lbl_pwr = status_pill("PWR ?", ORANGE)
        self.lbl_gps = status_pill("GPS —", GREEN)
        self.lbl_wifi = status_pill("WiFi —", CYAN)
        self.lbl_mesh = status_pill("MESH Off", RED)
        self.lbl_clk = status_pill("--:--", DIM)

        for w in (self.lbl_bat, self.lbl_pwr, self.lbl_gps, self.lbl_wifi, self.lbl_mesh, self.lbl_clk):
            bar.addWidget(w)

        return bar

    # ---- Page: Dashboard ----
    def _page_dashboard(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        # 2x2 grid
        grid = QGridLayout()
        grid.setSpacing(8)

        # AIS card
        card_ais, ais_lay = card_frame("AIS Vessels", CYAN)
        self.dash_ais = data_label("Waiting for AIS data...", DIM, True, 9)
        ais_lay.addWidget(self.dash_ais)
        grid.addWidget(card_ais, 0, 0)

        # DSC card
        card_dsc, dsc_lay = card_frame("DSC / Distress", ORANGE)
        self.dash_dsc = data_label("No DSC messages", DIM, True, 9)
        dsc_lay.addWidget(self.dash_dsc)
        grid.addWidget(card_dsc, 0, 1)

        # Pager card
        card_pgr, pgr_lay = card_frame("Pager / POCSAG", PURPLE)
        self.dash_pgr = data_label("No pager messages", DIM, True, 9)
        pgr_lay.addWidget(self.dash_pgr)
        grid.addWidget(card_pgr, 1, 0)

        # System status card
        card_sys, sys_lay = card_frame("System Status", GREEN)
        self.dash_aio = data_label("Loading...", DIM, True, 9)
        sys_lay.addWidget(self.dash_aio)
        grid.addWidget(card_sys, 1, 1)

        lay.addLayout(grid, 1)
        return page

    # ---- Page: Marine ----
    def _page_marine(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        # AIS tracking
        card_ais, ais_lay = card_frame("AIS Vessel Tracking", CYAN)
        self.marine_ais = data_label("Start iNTERCEPT to receive AIS data", DIM, True, 9)
        ais_lay.addWidget(self.marine_ais)
        btn_ais = action_btn("Start AIS (iNTERCEPT)", CYAN)
        btn_ais.clicked.connect(self._launch_intercept)
        ais_lay.addWidget(btn_ais)
        lay.addWidget(card_ais, 2)

        # DSC decoder
        card_dsc, dsc_lay = card_frame("DSC Distress Channel", ORANGE)
        self.marine_dsc = data_label("Channel 70 (156.525 MHz)\nDSC decoder available via iNTERCEPT", WHITE, True, 9)
        dsc_lay.addWidget(self.marine_dsc)
        btn_dsc = action_btn("Open iNTERCEPT Web UI", ORANGE)
        btn_dsc.clicked.connect(lambda: launch_browser("http://localhost:5050"))
        dsc_lay.addWidget(btn_dsc)
        lay.addWidget(card_dsc, 2)

        # VHF channels
        card_vhf, vhf_lay = card_frame("VHF Channel Monitor", GREEN)
        channels = "Ch 16 — 156.800 MHz (Distress)\nCh 70 — 156.525 MHz (DSC)\nCh 13 — 156.650 MHz (Bridge)\nCh 67 — 156.375 MHz (Port)"
        vhf_lay.addWidget(data_label(channels, WHITE, True, 9))
        lay.addWidget(card_vhf, 1)

        return page

    # ---- Page: Radio / SDR ----
    def _page_radio(self) -> QWidget:
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setStyleSheet(f"QScrollArea {{ border: none; background-color: {BG}; }}")
        inner = QWidget()
        inner.setStyleSheet(f"background-color: {BG};")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        # SIGINT
        card_sig, sig_lay = card_frame("SIGINT Platform", ORANGE)
        btn1 = action_btn("Start iNTERCEPT", ORANGE, 48, 12)
        btn1.clicked.connect(self._launch_intercept)
        sig_lay.addWidget(btn1)
        btn2 = action_btn("Open iNTERCEPT Web (port 5050)", CYAN)
        btn2.clicked.connect(lambda: launch_browser("http://localhost:5050"))
        sig_lay.addWidget(btn2)
        lay.addWidget(card_sig)

        # SDR tools
        card_sdr, sdr_lay = card_frame("SDR Tools", CYAN)
        row = QHBoxLayout()
        row.setSpacing(4)
        b1 = action_btn("SDR++", CYAN)
        b1.clicked.connect(self._launch_sdrpp)
        row.addWidget(b1)
        b2 = action_btn("tar1090", GREEN)
        b2.clicked.connect(self._launch_tar1090)
        row.addWidget(b2)
        sdr_lay.addLayout(row)
        b3 = action_btn("WSJT-X (FT8/FT4)", YELLOW)
        b3.clicked.connect(self._launch_wsjtx)
        sdr_lay.addWidget(b3)
        lay.addWidget(card_sdr)

        # Power monitor
        card_pwr, pwr_lay = card_frame("Power Monitor", ORANGE)
        b4 = action_btn("Live Power Monitor", ORANGE)
        b4.clicked.connect(lambda: launch_terminal("aiov2_ctl --power"))
        pwr_lay.addWidget(b4)
        lay.addWidget(card_pwr)

        lay.addStretch()
        page.setWidget(inner)
        return page

    # ---- Page: Mesh ----
    def _page_mesh(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        # Mesh mode
        card_mode, mode_lay = card_frame("Mesh Mode", GREEN)
        row = QHBoxLayout()
        row.setSpacing(4)
        b1 = action_btn("Meshtastic", GREEN)
        b1.clicked.connect(lambda: self._do_action("uconsole-radio meshtastic"))
        row.addWidget(b1)
        b2 = action_btn("MeshCore", PURPLE)
        b2.clicked.connect(lambda: self._do_action("uconsole-radio meshcore"))
        row.addWidget(b2)
        b3 = action_btn("Off", RED)
        b3.clicked.connect(lambda: self._do_action("uconsole-radio off"))
        row.addWidget(b3)
        mode_lay.addLayout(row)
        lay.addWidget(card_mode)

        # Mesh apps
        card_apps, apps_lay = card_frame("Mesh Apps", CYAN)
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        c1 = action_btn("Contact (TUI)", GREEN)
        c1.clicked.connect(self._launch_contact)
        row2.addWidget(c1)
        c2 = action_btn("MeshCore TUI", PURPLE)
        c2.clicked.connect(self._launch_mc_tui)
        row2.addWidget(c2)
        apps_lay.addLayout(row2)
        c3 = action_btn("MeshDash (port 8000)", CYAN)
        c3.clicked.connect(lambda: launch_browser("http://localhost:8000"))
        apps_lay.addWidget(c3)
        lay.addWidget(card_apps)

        # AIO toggles
        card_aio, aio_lay = card_frame("AIO Module Power", CYAN)
        self.mesh_aio_grid = QGridLayout()
        self.mesh_aio_grid.setSpacing(4)
        self.aio_buttons = {}
        for i, name in enumerate(["GPS", "SDR", "USB", "LORA"]):
            btn = toggle_btn(name, False)
            btn.clicked.connect(lambda _, n=name: self._toggle_aio(n))
            self.mesh_aio_grid.addWidget(btn, i // 2, i % 2)
            self.aio_buttons[name] = btn
        aio_lay.addLayout(self.mesh_aio_grid)
        lay.addWidget(card_aio)

        lay.addStretch()
        return page

    # ---- Page: System ----
    def _page_system(self) -> QWidget:
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setStyleSheet(f"QScrollArea {{ border: none; background-color: {BG}; }}")
        inner = QWidget()
        inner.setStyleSheet(f"background-color: {BG};")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        # GPS & Time
        card_gps, gps_lay = card_frame("GPS & Time", GREEN)
        row = QHBoxLayout()
        row.setSpacing(4)
        b1 = action_btn("PyGPSClient", GREEN)
        b1.clicked.connect(lambda: launch("pygpsclient 2>/dev/null &"))
        row.addWidget(b1)
        b2 = action_btn("Sync RTC", CYAN)
        b2.clicked.connect(self._sync_rtc)
        row.addWidget(b2)
        gps_lay.addLayout(row)
        lay.addWidget(card_gps)

        # Keyboard backlight
        card_kbd, kbd_lay = card_frame("Keyboard", YELLOW)
        self.btn_kbd = toggle_btn("Backlight", False)
        self.btn_kbd.clicked.connect(self._toggle_kbd)
        kbd_lay.addWidget(self.btn_kbd)
        lay.addWidget(card_kbd)

        # Diagnostics
        card_diag, diag_lay = card_frame("Diagnostics", ORANGE)
        b3 = action_btn("Run Diagnostics", ORANGE)
        b3.clicked.connect(lambda: launch_terminal("uconsole-doctor"))
        diag_lay.addWidget(b3)
        lay.addWidget(card_diag)

        # Tools
        card_tools, tools_lay = card_frame("Quick Tools", WHITE)
        row3 = QHBoxLayout()
        row3.setSpacing(4)
        b4 = action_btn("Terminal", WHITE)
        b4.clicked.connect(lambda: launch_terminal())
        row3.addWidget(b4)
        b5 = action_btn("AIO Tray GUI", CYAN)
        b5.clicked.connect(lambda: launch("aiov2_ctl --gui 2>/dev/null &"))
        row3.addWidget(b5)
        tools_lay.addLayout(row3)
        lay.addWidget(card_tools)

        # Power
        card_pwr, pwr_lay = card_frame("Power", RED)
        row4 = QHBoxLayout()
        row4.setSpacing(4)
        b6 = action_btn("Reboot", ORANGE, 40, 10)
        b6.clicked.connect(lambda: subprocess.run("sudo reboot", shell=True))
        row4.addWidget(b6)
        b7 = action_btn("Shutdown", RED, 40, 10)
        b7.clicked.connect(lambda: subprocess.run("sudo shutdown -h now", shell=True))
        row4.addWidget(b7)
        pwr_lay.addLayout(row4)
        lay.addWidget(card_pwr)

        lay.addStretch()
        page.setWidget(inner)
        return page

    # ---- Actions ----
    def _do_action(self, cmd: str) -> None:
        launch(f"sudo {cmd}")
        time.sleep(0.5)

    def _toggle_aio(self, name: str) -> None:
        current = self.aio_states.get(name, False)
        action = "off" if current else "on"
        if which("aiov2_ctl"):
            sudo_sh(f"aiov2_ctl {name} {action}")
        elif which("pinctrl"):
            pin_map = {"GPS": 27, "LORA": 16, "SDR": 7, "USB": 23}
            pin = pin_map.get(name)
            if pin:
                sudo_sh(f"pinctrl set {pin} op {'dh' if action == 'on' else 'dl'}")
        time.sleep(0.3)
        self._refresh_aio()

    def _toggle_kbd(self) -> None:
        for path in ("/sys/class/leds/kbd_backlight/brightness",
                     "/sys/class/leds/clockworkpi::kbd_backlight/brightness"):
            if Path(path).exists():
                current = int(sh(f"cat {path}") or "0")
                maxb = int(sh(f"cat {path.replace('brightness', 'max_brightness')}") or "1")
                new = "0" if current > 0 else str(maxb)
                sudo_sh(f"sh -c 'echo {new} > {path}'")
                time.sleep(0.2)
                self._refresh_kbd()
                return

    def _launch_contact(self) -> None:
        if which("contact"):
            launch_terminal("contact --port /dev/ttyUSB0")
        else:
            launch_terminal("pipx install contact && contact --port /dev/ttyUSB0")

    def _launch_mc_tui(self) -> None:
        if which("tui-meshcore"):
            launch_terminal("tui-meshcore")
        else:
            launch_terminal("pipx install git+https://github.com/guax/tui-meshcore.git && tui-meshcore")

    def _launch_intercept(self) -> None:
        if Path("/opt/intercept/start.sh").exists():
            launch("cd /opt/intercept && sudo ./start.sh")
            time.sleep(2)
            launch_browser("http://localhost:5050")
        else:
            launch_terminal("echo 'iNTERCEPT not installed'")

    def _launch_sdrpp(self) -> None:
        if which("sdrpp-brown"):
            launch("sdrpp-brown &")
        elif which("sdrpp"):
            launch("sdrpp &")
        else:
            launch_terminal("echo 'SDR++ not installed'")

    def _launch_tar1090(self) -> None:
        if sh("systemctl is-active readsb 2>/dev/null") != "active":
            sudo_sh("systemctl start readsb 2>/dev/null")
        launch_browser("http://localhost/tar1090")

    def _launch_wsjtx(self) -> None:
        if which("wsjtx"):
            launch("wsjtx &")
        else:
            launch_terminal("echo 'WSJT-X not installed. Run: sudo apt install wsjtx'")

    def _sync_rtc(self) -> None:
        launch_terminal("sudo aiov2_ctl --sync-rtc && echo 'RTC synced.' && sleep 2")

    # ---- Timers ----
    def _start_timers(self) -> None:
        self._refresh_status()
        self._refresh_aio()
        self._refresh_kbd()
        self.timer = QTimer()
        self.timer.timeout.connect(self._refresh_status)
        self.timer.start(3000)
        self.timer_aio = QTimer()
        self.timer_aio.timeout.connect(self._refresh_aio)
        self.timer_aio.start(4000)
        self.timer_kbd = QTimer()
        self.timer_kbd.timeout.connect(self._refresh_kbd)
        self.timer_kbd.start(5000)

    def _refresh_status(self) -> None:
        bat = get_battery()
        ac = get_ac()
        bc = GREEN if bat["capacity"] != "?" and int(bat["capacity"]) > 30 else RED
        if ac: bc = CYAN
        self.lbl_bat.setText(f"BAT {bat['capacity']}%")
        self.lbl_bat.setStyleSheet(f"QLabel {{ background-color: {bc}18; color: {bc}; border: 1px solid {bc}50; border-radius: 10px; padding: 2px 8px; }}")
        self.lbl_pwr.setText(f"PWR {bat['power']}")
        wifi = get_wifi()
        self.lbl_wifi.setText(f"WiFi {wifi['ssid']}")
        self.lbl_clk.setText(time.strftime("%H:%M"))
        mode = get_mesh_mode()
        mc = GREEN if mode == "Meshtastic" else PURPLE if mode == "MeshCore" else RED
        self.lbl_mesh.setText(f"MESH {mode}")
        self.lbl_mesh.setStyleSheet(f"QLabel {{ background-color: {mc}18; color: {mc}; border: 1px solid {mc}50; border-radius: 10px; padding: 2px 8px; }}")
        # GPS
        if sh("systemctl is-active gpsd 2>/dev/null") == "active":
            self.lbl_gps.setText("GPS ON")
            self.lbl_gps.setStyleSheet(f"QLabel {{ background-color: {GREEN}18; color: {GREEN}; border: 1px solid {GREEN}50; border-radius: 10px; padding: 2px 8px; }}")
        else:
            self.lbl_gps.setText("GPS OFF")
            self.lbl_gps.setStyleSheet(f"QLabel {{ background-color: {RED}18; color: {RED}; border: 1px solid {RED}50; border-radius: 10px; padding: 2px 8px; }}")

        # Update dashboard data
        self._refresh_dashboard()

    def _refresh_aio(self) -> None:
        if self._building: return
        self._building = True
        new = get_aio_state()
        self.aio_states = new
        for name, btn in self.aio_buttons.items():
            is_on = new.get(name, False)
            c = GREEN if is_on else RED
            btn.blockSignals(True)
            btn.setText(f"{name}  {'●' if is_on else '○'}")
            btn.setStyleSheet(f"QPushButton {{ background-color: {c}18; color: {c}; border: 1px solid {c}80; border-radius: 6px; }} QPushButton:hover {{ background-color: {c}30; }} QPushButton:pressed {{ background-color: {c}; color: {BG}; }}")
            btn.blockSignals(False)
        self._building = False

    def _refresh_kbd(self) -> None:
        is_on = get_kb_backlight()
        c = YELLOW if is_on else RED
        self.btn_kbd.blockSignals(True)
        self.btn_kbd.setText(f"Backlight  {'●' if is_on else '○'}")
        self.btn_kbd.setStyleSheet(f"QPushButton {{ background-color: {c}18; color: {c}; border: 1px solid {c}80; border-radius: 6px; }} QPushButton:hover {{ background-color: {c}30; }}")
        self.btn_kbd.blockSignals(False)

    def _refresh_dashboard(self) -> None:
        # Update dashboard AIO summary
        states = self.aio_states
        lines = []
        for name in ["GPS", "SDR", "USB", "LORA"]:
            on = states.get(name, False)
            c = "●" if on else "○"
            lines.append(f"{name:5s} {c} {'ON ' if on else 'OFF'}")
        lines.append(f"Mesh: {get_mesh_mode()}")
        lines.append(f"VNC: {get_vnc_status()}")
        lines.append(f"Bat: {get_battery()['capacity']}%  PWR: {get_battery()['power']}")
        self.dash_aio.setText("\n".join(lines))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("uConsole Marine Console")
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(WHITE))
    app.setPalette(pal)
    win = MarineConsole()
    # Select dashboard by default
    win._switch_page("dashboard")
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
