#!/usr/bin/env python3
"""
uConsole Marine Console — modern dark dashboard for the uConsole CM5.

Sidebar navigation, card-based layout, real-time status bar.
Designed for 1280x720.  Borderless, dark navy theme.
One SDR — decode modes switch via iNTERCEPT.
"""

from __future__ import annotations
import os, subprocess, sys, time
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QLabel, QFrame, QSizePolicy,
    QStackedWidget, QScrollArea,
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
            full = f"{term} -e bash -c '{cmd}; exec bash'" if cmd else term
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

# Font sizes — bigger for 5" screen readability
FS_TITLE  = 11   # card section titles
FS_BODY   = 11   # body text / data labels
FS_BTN    = 12   # buttons
FS_NAV    = 22   # sidebar icons
FS_STATUS = 10   # status pills
FS_BIG   = 14   # prominent buttons

# ---------------------------------------------------------------------------
# UI builders
# ---------------------------------------------------------------------------
def card_frame(title: str = "", color: str = CYAN) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setStyleSheet(f"QFrame {{ background-color: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; }}")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(12, 10, 12, 10)
    lay.setSpacing(6)
    if title:
        lbl = QLabel(title.upper())
        lbl.setFont(QFont(FONT, FS_TITLE, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {color}; letter-spacing: 1px; padding-bottom: 4px; border: none;")
        lay.addWidget(lbl)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {BORDER}; border: none;")
        lay.addWidget(line)
    return frame, lay

def status_pill(text: str, color: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont(FONT, FS_STATUS, QFont.Weight.Bold))
    lbl.setStyleSheet(f"QLabel {{ background-color: {color}18; color: {color}; border: 1px solid {color}50; border-radius: 10px; padding: 3px 10px; }}")
    return lbl

def action_btn(text: str, color: str = CYAN, h: int = 48, fs: int = FS_BTN) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(h)
    btn.setFont(QFont(FONT, fs, QFont.Weight.Bold))
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {PANEL}; color: {color};
            border: 1px solid {color}50; border-radius: 6px; padding: 6px 12px;
        }}
        QPushButton:hover {{ background-color: {color}20; border: 1px solid {color}; }}
        QPushButton:pressed {{ background-color: {color}; color: {BG}; }}
    """)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return btn

def toggle_btn(name: str, is_on: bool, h: int = 48) -> QPushButton:
    c = GREEN if is_on else RED
    btn = QPushButton(f"{name}  {'●' if is_on else '○'}")
    btn.setFixedHeight(h)
    btn.setFont(QFont(FONT, FS_BTN, QFont.Weight.Bold))
    btn.setStyleSheet(f"""
        QPushButton {{ background-color: {c}18; color: {c}; border: 1px solid {c}80; border-radius: 6px; }}
        QPushButton:hover {{ background-color: {c}30; }}
        QPushButton:pressed {{ background-color: {c}; color: {BG}; }}
    """)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return btn

def sidebar_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedSize(64, 64)
    btn.setFont(QFont(FONT, FS_NAV, QFont.Weight.Bold))
    btn.setStyleSheet(f"""
        QPushButton {{ background-color: transparent; color: {DIM}; border: none; border-radius: 14px; }}
        QPushButton:hover {{ background-color: {CYAN}15; color: {WHITE}; }}
        QPushButton:checked {{ background-color: {CYAN}25; color: {CYAN}; border: 1px solid {CYAN}80; }}
    """)
    btn.setCheckable(True)
    return btn

def data_label(text: str, color: str = WHITE, mono: bool = False, size: int = FS_BODY) -> QLabel:
    lbl = QLabel(text)
    f = MONO if mono else FONT
    lbl.setFont(QFont(f, size))
    lbl.setStyleSheet(f"color: {color}; border: none;")
    lbl.setWordWrap(True)
    return lbl

def nav_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFixedHeight(16)
    lbl.setFont(QFont(FONT, 7))
    lbl.setStyleSheet(f"color: {DIM}; border: none;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        root.addLayout(self._build_sidebar())
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
        wrap = QFrame()
        wrap.setStyleSheet(f"background-color: {SIDEBAR}; border-right: 1px solid {BORDER};")
        wrap.setFixedWidth(84)
        bar = QVBoxLayout(wrap)
        bar.setContentsMargins(10, 12, 10, 12)
        bar.setSpacing(4)
        bar.setAlignment(Qt.AlignmentFlag.AlignTop)

        logo = QLabel("◆")
        logo.setFixedHeight(56)
        logo.setFont(QFont(FONT, 22, QFont.Weight.Black))
        logo.setStyleSheet(f"color: {CYAN}; border: none;")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(logo)

        self.nav_buttons = {}
        pages = [
            ("dashboard", "⌂", "Dash"),
            ("marine",    "⚓", "Marine"),
            ("radio",      "📡", "SDR"),
            ("mesh",       "📻", "Mesh"),
            ("system",     "⚙", "System"),
        ]
        for key, icon, label in pages:
            btn = sidebar_btn(icon)
            btn.setToolTip(label)
            btn.clicked.connect(lambda _, k=key: self._switch_page(k))
            bar.addWidget(btn)
            self.nav_buttons[key] = btn
            bar.addWidget(nav_label(label))

        bar.addStretch()

        btn_exit = QPushButton("✕")
        btn_exit.setFixedSize(64, 64)
        btn_exit.setFont(QFont(FONT, FS_NAV, QFont.Weight.Bold))
        btn_exit.setStyleSheet(f"QPushButton {{ background-color: transparent; color: {RED}80; border: none; border-radius: 14px; }} QPushButton:hover {{ background-color: {RED}20; color: {RED}; }}")
        btn_exit.setToolTip("Exit to Desktop")
        btn_exit.clicked.connect(self.close)
        bar.addWidget(btn_exit)
        bar.addWidget(nav_label("Exit"))

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(wrap)
        return outer

    def _switch_page(self, key: str) -> None:
        idx = ["dashboard", "marine", "radio", "mesh", "system"].index(key)
        self.stack.setCurrentIndex(idx)
        for k, btn in self.nav_buttons.items():
            btn.setChecked(k == key)

    # ---- Status bar ----
    def _build_status_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setContentsMargins(16, 8, 16, 8)
        bar.setSpacing(10)
        title = QLabel("MARINE CONSOLE")
        title.setFont(QFont(FONT, FS_TITLE, QFont.Weight.Black))
        title.setStyleSheet(f"color: {CYAN}; letter-spacing: 2px; border: none;")
        bar.addWidget(title)
        bar.addStretch()
        self.lbl_bat  = status_pill("BAT ?%", GREEN)
        self.lbl_pwr  = status_pill("PWR ?", ORANGE)
        self.lbl_gps  = status_pill("GPS —", RED)
        self.lbl_wifi = status_pill("WiFi —", CYAN)
        self.lbl_mesh = status_pill("MESH Off", RED)
        self.lbl_clk  = status_pill("--:--", DIM)
        for w in (self.lbl_bat, self.lbl_pwr, self.lbl_gps, self.lbl_wifi, self.lbl_mesh, self.lbl_clk):
            bar.addWidget(w)
        return bar

    # ---- Page: Dashboard ----
    def _page_dashboard(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(10)

        # SDR status card — the one SDR can only do one thing at a time
        card_sdr, sdr_lay = card_frame("SDR Status (1× RTL-SDR)", CYAN)
        self.dash_sdr = data_label(
            "SDR is OFF — turn on in Mesh tab\n\n"
            "One SDR = one decode mode at a time:\n"
            "• AIS vessel tracking (162 MHz)\n"
            "• DSC distress (156.525 MHz)\n"
            "• Pager POCSAG/FLEX\n"
            "• 433 MHz sensors\n"
            "• ADS-B aircraft (1090 MHz)\n\n"
            "Use iNTERCEPT to switch modes.", WHITE, True, FS_BODY
        )
        sdr_lay.addWidget(self.dash_sdr)
        grid.addWidget(card_sdr, 0, 0)

        # System card
        card_sys, sys_lay = card_frame("System", GREEN)
        self.dash_sys = data_label("Loading...", DIM, True, FS_BODY)
        sys_lay.addWidget(self.dash_sys)
        grid.addWidget(card_sys, 0, 1)

        # Quick launch card
        card_q, q_lay = card_frame("Quick Launch", ORANGE)
        row = QHBoxLayout()
        row.setSpacing(6)
        b1 = action_btn("iNTERCEPT", ORANGE)
        b1.clicked.connect(self._launch_intercept)
        row.addWidget(b1)
        b2 = action_btn("SDR++", CYAN)
        b2.clicked.connect(self._launch_sdrpp)
        row.addWidget(b2)
        q_lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        b3 = action_btn("WSJT-X", YELLOW)
        b3.clicked.connect(self._launch_wsjtx)
        row2.addWidget(b3)
        b4 = action_btn("Terminal", WHITE)
        b4.clicked.connect(lambda: launch_terminal())
        row2.addWidget(b4)
        q_lay.addLayout(row2)
        grid.addWidget(card_q, 1, 0)

        # Mesh status card
        card_m, m_lay = card_frame("Mesh Status", PURPLE)
        self.dash_mesh = data_label("Loading...", DIM, True, FS_BODY)
        m_lay.addWidget(self.dash_mesh)
        grid.addWidget(card_m, 1, 1)

        lay.addLayout(grid, 1)
        return page

    # ---- Page: Marine ----
    def _page_marine(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        # SDR mode note
        card_note, note_lay = card_frame("⚠ One SDR Limitation", YELLOW)
        note_lay.addWidget(data_label(
            "The uConsole has one RTL-SDR. You can decode AIS, DSC, or Pager —\n"
            "but only ONE at a time. iNTERCEPT manages the SDR and lets you\n"
            "switch between decode modes from its web UI (port 5050).",
            WHITE, False, FS_BODY
        ))
        lay.addWidget(card_note)

        # AIS
        card_ais, ais_lay = card_frame("AIS Vessel Tracking", CYAN)
        ais_lay.addWidget(data_label(
            "AIS uses 161.975 MHz (Ch 87B) and 162.025 MHz (Ch 88B).\n"
            "Start iNTERCEPT → AIS mode to track vessels within ~20nm.\n"
            "Vessels shown on the iNTERCEPT web map with course, speed, MMSI.",
            WHITE, True, FS_BODY
        ))
        btn_ais = action_btn("Start iNTERCEPT (AIS mode)", CYAN, 48, FS_BTN)
        btn_ais.clicked.connect(self._launch_intercept)
        ais_lay.addWidget(btn_ais)
        lay.addWidget(card_ais)

        # DSC
        card_dsc, dsc_lay = card_frame("DSC Distress Channel", ORANGE)
        dsc_lay.addWidget(data_label(
            "DSC uses Channel 70 (156.525 MHz).\n"
            "iNTERCEPT decodes DSC distress, urgency, safety, and routine calls.\n"
            "Messages shown in iNTERCEPT web UI with MMSI, type, and timestamp.",
            WHITE, True, FS_BODY
        ))
        btn_dsc = action_btn("Open iNTERCEPT Web UI", ORANGE, 48, FS_BTN)
        btn_dsc.clicked.connect(lambda: launch_browser("http://localhost:5050"))
        dsc_lay.addWidget(btn_dsc)
        lay.addWidget(card_dsc)

        # VHF reference
        card_vhf, vhf_lay = card_frame("VHF Channel Reference", GREEN)
        vhf_lay.addWidget(data_label(
            "Ch 16  156.800 MHz  Distress/Safety\n"
            "Ch 70  156.525 MHz  DSC Digital Selective Calling\n"
            "Ch 13  156.650 MHz  Bridge-to-bridge\n"
            "Ch 67  156.375 MHz  Port operations\n"
            "Ch 87B 161.975 MHz  AIS 1\n"
            "Ch 88B 162.025 MHz  AIS 2",
            WHITE, True, FS_BODY
        ))
        lay.addWidget(card_vhf)

        lay.addStretch()
        return page

    # ---- Page: Radio / SDR ----
    def _page_radio(self) -> QWidget:
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setStyleSheet(f"QScrollArea {{ border: none; background-color: {BG}; }}")
        inner = QWidget()
        inner.setStyleSheet(f"background-color: {BG};")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        card_sig, sig_lay = card_frame("SIGINT Platform", ORANGE)
        b1 = action_btn("Start iNTERCEPT", ORANGE, 56, FS_BIG)
        b1.clicked.connect(self._launch_intercept)
        sig_lay.addWidget(b1)
        b2 = action_btn("Open iNTERCEPT Web UI (port 5050)", CYAN, 48, FS_BTN)
        b2.clicked.connect(lambda: launch_browser("http://localhost:5050"))
        sig_lay.addWidget(b2)
        sig_lay.addWidget(data_label(
            "iNTERCEPT manages the SDR. It can decode:\n"
            "AIS, DSC, Pager, 433 MHz, ADS-B, ACARS, VDL2, APRS,\n"
            "Weather Sat, SSTV, WiFi, Bluetooth, GPS, and more.",
            DIM, False, FS_BODY
        ))
        lay.addWidget(card_sig)

        card_sdr, sdr_lay = card_frame("SDR Tools", CYAN)
        row = QHBoxLayout()
        row.setSpacing(6)
        s1 = action_btn("SDR++", CYAN, 48, FS_BTN)
        s1.clicked.connect(self._launch_sdrpp)
        row.addWidget(s1)
        s2 = action_btn("tar1090 (ADS-B)", GREEN, 48, FS_BTN)
        s2.clicked.connect(self._launch_tar1090)
        row.addWidget(s2)
        sdr_lay.addLayout(row)
        s3 = action_btn("WSJT-X (FT8/FT4/JT modes)", YELLOW, 48, FS_BTN)
        s3.clicked.connect(self._launch_wsjtx)
        sdr_lay.addWidget(s3)
        lay.addWidget(card_sdr)

        card_pwr, pwr_lay = card_frame("Power Monitor", ORANGE)
        p1 = action_btn("Live Power Monitor", ORANGE, 48, FS_BTN)
        p1.clicked.connect(lambda: launch_terminal("aiov2_ctl --power"))
        pwr_lay.addWidget(p1)
        lay.addWidget(card_pwr)

        lay.addStretch()
        page.setWidget(inner)
        return page

    # ---- Page: Mesh ----
    def _page_mesh(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        card_mode, mode_lay = card_frame("Mesh Mode", GREEN)
        row = QHBoxLayout()
        row.setSpacing(6)
        m1 = action_btn("Meshtastic", GREEN, 52, FS_BTN)
        m1.clicked.connect(lambda: self._do_action("uconsole-radio meshtastic"))
        row.addWidget(m1)
        m2 = action_btn("MeshCore", PURPLE, 52, FS_BTN)
        m2.clicked.connect(lambda: self._do_action("uconsole-radio meshcore"))
        row.addWidget(m2)
        m3 = action_btn("Off", RED, 52, FS_BTN)
        m3.clicked.connect(lambda: self._do_action("uconsole-radio off"))
        row.addWidget(m3)
        mode_lay.addLayout(row)
        lay.addWidget(card_mode)

        card_apps, apps_lay = card_frame("Mesh Apps", CYAN)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        a1 = action_btn("Contact (TUI)", GREEN, 48, FS_BTN)
        a1.clicked.connect(self._launch_contact)
        row2.addWidget(a1)
        a2 = action_btn("MeshCore TUI", PURPLE, 48, FS_BTN)
        a2.clicked.connect(self._launch_mc_tui)
        row2.addWidget(a2)
        apps_lay.addLayout(row2)
        a3 = action_btn("MeshDash (port 8000)", CYAN, 48, FS_BTN)
        a3.clicked.connect(lambda: launch_browser("http://localhost:8000"))
        apps_lay.addWidget(a3)
        lay.addWidget(card_apps)

        card_aio, aio_lay = card_frame("AIO Module Power", CYAN)
        self.aio_buttons = {}
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, name in enumerate(["GPS", "SDR", "USB", "LORA"]):
            btn = toggle_btn(name, False)
            btn.clicked.connect(lambda _, n=name: self._toggle_aio(n))
            grid.addWidget(btn, i // 2, i % 2)
            self.aio_buttons[name] = btn
        aio_lay.addLayout(grid)
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
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        card_gps, gps_lay = card_frame("GPS & Time", GREEN)
        row = QHBoxLayout()
        row.setSpacing(6)
        g1 = action_btn("PyGPSClient", GREEN, 48, FS_BTN)
        g1.clicked.connect(lambda: launch("pygpsclient 2>/dev/null &"))
        row.addWidget(g1)
        g2 = action_btn("Sync RTC", CYAN, 48, FS_BTN)
        g2.clicked.connect(self._sync_rtc)
        row.addWidget(g2)
        gps_lay.addLayout(row)
        lay.addWidget(card_gps)

        card_kbd, kbd_lay = card_frame("Keyboard", YELLOW)
        self.btn_kbd = toggle_btn("Backlight", False)
        self.btn_kbd.clicked.connect(self._toggle_kbd)
        kbd_lay.addWidget(self.btn_kbd)
        lay.addWidget(card_kbd)

        card_diag, diag_lay = card_frame("Diagnostics", ORANGE)
        d1 = action_btn("Run Diagnostics", ORANGE, 48, FS_BTN)
        d1.clicked.connect(lambda: launch_terminal("uconsole-doctor"))
        diag_lay.addWidget(d1)
        lay.addWidget(card_diag)

        card_tools, tools_lay = card_frame("Quick Tools", WHITE)
        row3 = QHBoxLayout()
        row3.setSpacing(6)
        t1 = action_btn("Terminal", WHITE, 48, FS_BTN)
        t1.clicked.connect(lambda: launch_terminal())
        row3.addWidget(t1)
        t2 = action_btn("AIO Tray GUI", CYAN, 48, FS_BTN)
        t2.clicked.connect(lambda: launch("aiov2_ctl --gui 2>/dev/null &"))
        row3.addWidget(t2)
        tools_lay.addLayout(row3)
        lay.addWidget(card_tools)

        card_pwr, pwr_lay = card_frame("Power", RED)
        row4 = QHBoxLayout()
        row4.setSpacing(6)
        p1 = action_btn("Reboot", ORANGE, 48, FS_BTN)
        p1.clicked.connect(lambda: subprocess.run("sudo reboot", shell=True))
        row4.addWidget(p1)
        p2 = action_btn("Shutdown", RED, 48, FS_BTN)
        p2.clicked.connect(lambda: subprocess.run("sudo shutdown -h now", shell=True))
        row4.addWidget(p2)
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
        self.lbl_bat.setStyleSheet(f"QLabel {{ background-color: {bc}18; color: {bc}; border: 1px solid {bc}50; border-radius: 10px; padding: 3px 10px; }}")
        self.lbl_pwr.setText(f"PWR {bat['power']}")
        wifi = get_wifi()
        self.lbl_wifi.setText(f"WiFi {wifi['ssid']}")
        self.lbl_clk.setText(time.strftime("%H:%M"))
        mode = get_mesh_mode()
        mc = GREEN if mode == "Meshtastic" else PURPLE if mode == "MeshCore" else RED
        self.lbl_mesh.setText(f"MESH {mode}")
        self.lbl_mesh.setStyleSheet(f"QLabel {{ background-color: {mc}18; color: {mc}; border: 1px solid {mc}50; border-radius: 10px; padding: 3px 10px; }}")
        if sh("systemctl is-active gpsd 2>/dev/null") == "active":
            self.lbl_gps.setText("GPS ON")
            self.lbl_gps.setStyleSheet(f"QLabel {{ background-color: {GREEN}18; color: {GREEN}; border: 1px solid {GREEN}50; border-radius: 10px; padding: 3px 10px; }}")
        else:
            self.lbl_gps.setText("GPS OFF")
            self.lbl_gps.setStyleSheet(f"QLabel {{ background-color: {RED}18; color: {RED}; border: 1px solid {RED}50; border-radius: 10px; padding: 3px 10px; }}")
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
        # SDR status
        states = self.aio_states
        sdr_on = states.get("SDR", False)
        if sdr_on:
            self.dash_sdr.setText(
                "SDR is ON ● Ready to decode\n\n"
                "One SDR = one decode mode at a time:\n"
                "• AIS vessel tracking (162 MHz)\n"
                "• DSC distress (156.525 MHz)\n"
                "• Pager POCSAG/FLEX\n"
                "• 433 MHz sensors\n"
                "• ADS-B aircraft (1090 MHz)\n\n"
                "Use iNTERCEPT to select decode mode."
            )
            self.dash_sdr.setStyleSheet(f"color: {GREEN}; border: none;")
        else:
            self.dash_sdr.setStyleSheet(f"color: {DIM}; border: none;")

        # System summary
        lines = []
        for name in ["GPS", "SDR", "USB", "LORA"]:
            on = states.get(name, False)
            lines.append(f"{name:5s} {'● ON ' if on else '○ OFF'}")
        lines.append(f"")
        lines.append(f"Mesh: {get_mesh_mode()}")
        lines.append(f"Bat: {get_battery()['capacity']}%  PWR: {get_battery()['power']}")
        lines.append(f"WiFi: {get_wifi()['ssid']}")
        self.dash_sys.setText("\n".join(lines))

        # Mesh status
        mode = get_mesh_mode()
        mesh_lines = [
            f"Mode: {mode}",
            f"",
            f"Meshtastic — long-range LoRa mesh",
            f"MeshCore  — decentralised mesh comms",
            f"",
            f"Apps:",
            f"  Contact  — Meshtastic TUI chat",
            f"  MeshCore TUI — MeshCore TUI chat",
            f"  MeshDash — web dashboard (port 8000)",
        ]
        self.dash_mesh.setText("\n".join(mesh_lines))

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
    win._switch_page("dashboard")
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
