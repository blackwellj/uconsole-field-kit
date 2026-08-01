#!/usr/bin/env python3
"""
uConsole Field Launcher — a fullscreen PyQt6 kiosk UI for the
ClockworkPi uConsole CM5 with HackerGadgets AIO V2 board.

Designed for 1280x720.  Borderless, dark-themed, touch-friendly.
Exit button reveals the full desktop underneath.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QLabel, QFrame, QSizePolicy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sh(cmd: str, timeout: int = 5) -> str:
    """Run a shell command, return stdout (empty string on failure)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception:
        return ""

def sudo_sh(cmd: str, timeout: int = 5) -> str:
    """Run a shell command with sudo."""
    return sh(f"sudo -n {cmd}", timeout=timeout)

def get_battery() -> dict:
    """Read battery info from kernel power_supply sysfs."""
    info = {"capacity": "?", "status": "?", "voltage": "?", "power": "?", "current": "?"}
    base = "/sys/class/power_supply"
    for supply in ("axp20x-battery", "axp22x-battery", "BAT0", "BAT1"):
        p = Path(base) / supply
        if p.is_dir():
            cap = sh(f"cat {p}/capacity 2>/dev/null")
            stat = sh(f"cat {p}/status 2>/dev/null")
            vnow = sh(f"cat {p}/voltage_now 2>/dev/null")
            inow = sh(f"cat {p}/current_now 2>/dev/null")
            if cap:
                info["capacity"] = cap
            if stat:
                info["status"] = stat
            if vnow:
                try:
                    info["voltage"] = f"{int(vnow) / 1_000_000:.2f}V"
                except ValueError:
                    pass
            if inow:
                try:
                    ma = int(inow) / 1_000_000
                    info["current"] = f"{ma:.2f}A"
                    if "voltage" in info and info["voltage"] != "?":
                        v = float(info["voltage"].rstrip("V"))
                        info["power"] = f"{abs(ma * v):.2f}W"
                except ValueError:
                    pass
            break
    return info

def get_ac_online() -> bool:
    for supply in ("axp22x-ac", "AC0", "ADP1"):
        p = Path(f"/sys/class/power_supply/{supply}/online")
        if p.exists():
            return sh(f"cat {p}") == "1"
    return False

def get_wifi_info() -> dict:
    info = {"ssid": "—", "ip": "—"}
    ssid = sh("iwgetid -r 2>/dev/null") or sh("nmcli -t -f active,ssid dev wifi 2>/dev/null | grep '^yes' | cut -d: -f2")
    if ssid:
        info["ssid"] = ssid
    # Get primary IP
    ip = sh("ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1")
    if ip:
        info["ip"] = ip
    return info

def get_aio_state() -> dict:
    """Get GPS/SDR/USB/LoRa on/off state via aiov2_ctl or pinctrl."""
    states = {}
    if shutil_which("aiov2_ctl"):
        out = sh("aiov2_ctl 2>/dev/null")
        # Output format: "GPS: ON\nLORA: OFF\n..."
        for line in out.splitlines():
            if ":" in line:
                name, state = line.split(":", 1)
                name = name.strip().upper()
                state = state.strip().upper()
                states[name] = state == "ON"
    else:
        # Fallback to pinctrl
        pin_map = {"GPS": 27, "LORA": 16, "SDR": 7, "USB": 23}
        for name, pin in pin_map.items():
            out = sh(f"pinctrl get {pin} 2>/dev/null")
            states[name] = "hi" in out.lower()
    return states

def get_mesh_mode() -> str:
    """Detect which mesh service is currently active."""
    for unit, label in [
        ("meshtasticd.service", "Meshtastic"),
        ("meshcore.service", "MeshCore"),
        ("meshcore-uconsole.service", "MeshCore"),
        ("meshcore-gui.service", "MeshCore"),
    ]:
        if sh(f"systemctl is-active --quiet {unit} 2>/dev/null") or sudo_sh(f"systemctl is-active --quiet {unit}") == "":
            if sh(f"systemctl is-active {unit} 2>/dev/null") == "active" or sudo_sh(f"systemctl is-active {unit}") == "active":
                return label
    return "Off"

def shutil_which(cmd: str) -> bool:
    return sh(f"command -v {cmd}") != ""

def launch(cmd: str, background: bool = True) -> None:
    """Launch a command in the background (non-blocking)."""
    if background:
        subprocess.Popen(cmd, shell=True, start_new_session=True)
    else:
        subprocess.Popen(cmd, shell=True)

def launch_terminal(cmd: str = "") -> None:
    """Open a terminal window with an optional pre-run command."""
    for term in ("x-terminal-emulator", "qterminal", "lxterminal", "xterm"):
        if shutil_which(term):
            full = f"{term} -e bash -c '{cmd}; exec bash'" if cmd else term
            launch(full)
            return
    launch(f"xterm -e '{cmd}'" if cmd else "xterm")

def launch_browser(url: str) -> None:
    for browser in ("x-www-browser", "chromium", "firefox", "epiphany", "dillo"):
        if shutil_which(browser):
            launch(f"{browser} {url}")
            return
    launch(f"xdg-open {url}")

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

DARK_BG = "#0a0a0f"
PANEL_BG = "#15151f"
PANEL_BORDER = "#2a2a3a"
ACCENT_CYAN = "#00d9ff"
ACCENT_GREEN = "#00ff88"
ACCENT_RED = "#ff3366"
ACCENT_ORANGE = "#ff8c1a"
ACCENT_PURPLE = "#b060ff"
TEXT_PRIMARY = "#e0e0f0"
TEXT_DIM = "#606078"
FONT_FAMILY = "DejaVu Sans"

def styled_button(text: str, color: str = ACCENT_CYAN, icon: str = "") -> QPushButton:
    btn = QPushButton(f"{icon}  {text}" if icon else text)
    btn.setFixedHeight(64)
    btn.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.Bold))
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {PANEL_BG};
            color: {color};
            border: 2px solid {color}40;
            border-radius: 10px;
            padding: 8px 16px;
            text-align: center;
        }}
        QPushButton:hover {{
            background-color: {color}18;
            border: 2px solid {color};
        }}
        QPushButton:pressed {{
            background-color: {color}30;
        }}
    """)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return btn

def section_label(text: str, color: str = TEXT_DIM) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont(FONT_FAMILY, 9, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color: {color}; padding: 4px 0 2px 4px;")
    return lbl

def status_pill(text: str, color: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
    lbl.setStyleSheet(f"""
        background-color: {color}20;
        color: {color};
        border: 1px solid {color}60;
        border-radius: 12px;
        padding: 3px 10px;
    """)
    return lbl

def toggle_button(name: str, is_on: bool) -> QPushButton:
    color = ACCENT_GREEN if is_on else ACCENT_RED
    state_text = "ON" if is_on else "OFF"
    btn = QPushButton(f"{name}\n{state_text}")
    btn.setFixedHeight(60)
    btn.setFont(QFont(FONT_FAMILY, 9, QFont.Weight.Bold))
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {color}18;
            color: {color};
            border: 2px solid {color};
            border-radius: 10px;
            text-align: center;
        }}
        QPushButton:hover {{
            background-color: {color}30;
        }}
    """)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return btn

# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class FieldLauncher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("uConsole Field Launcher")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.resize(1280, 720)

        self.aio_states = {}
        self.mesh_mode = "Off"
        self._building_toggles = False

        self._build_ui()
        self._start_timers()

    # ---- UI construction ----

    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet(f"background-color: {DARK_BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(6)

        # --- Top status bar ---
        root.addLayout(self._build_status_bar())

        # --- Main grid ---
        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 4, 0, 0)

        # Column 0: AIO toggles
        grid.addLayout(self._build_aio_panel(), 0, 0)

        # Column 1: Mesh + comms
        grid.addLayout(self._build_mesh_panel(), 0, 1)

        # Column 2: SDR + SIGINT
        grid.addLayout(self._build_sdr_panel(), 0, 2)

        # Column 3: GPS + system
        grid.addLayout(self._build_system_panel(), 0, 3)

        root.addLayout(grid, 1)

        # --- Bottom bar ---
        root.addLayout(self._build_bottom_bar())

    def _build_status_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)

        # Title
        title = QLabel("◆ uCONSOLE FIELD KIT")
        title.setFont(QFont(FONT_FAMILY, 12, QFont.Weight.Black))
        title.setStyleSheet(f"color: {ACCENT_CYAN}; letter-spacing: 2px;")
        bar.addWidget(title)

        bar.addStretch()

        self.lbl_battery = status_pill("BAT ?%", ACCENT_GREEN)
        self.lbl_power = status_pill("⚡ ?W", ACCENT_ORANGE)
        self.lbl_wifi = status_pill("WiFi —", ACCENT_CYAN)
        self.lbl_ip = status_pill("IP —", ACCENT_PURPLE)
        self.lbl_mesh = status_pill("MESH Off", ACCENT_ORANGE)
        self.lbl_clock = status_pill("--:--", TEXT_DIM)

        for w in (self.lbl_battery, self.lbl_power, self.lbl_wifi, self.lbl_ip, self.lbl_mesh, self.lbl_clock):
            bar.addWidget(w)

        return bar

    def _build_aio_panel(self) -> QVBoxLayout:
        panel = QVBoxLayout()
        panel.setSpacing(4)

        panel.addWidget(section_label("◈ AIO V2 MODULES", ACCENT_CYAN))

        frame = QFrame()
        frame.setStyleSheet(f"background-color: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; border-radius: 10px;")
        flay = QGridLayout(frame)
        flay.setSpacing(6)
        flay.setContentsMargins(8, 8, 8, 8)

        self.aio_buttons = {}
        for i, name in enumerate(["GPS", "SDR", "USB", "LORA"]):
            btn = toggle_button(name, False)
            btn.clicked.connect(lambda _, n=name: self._toggle_aio(n))
            flay.addWidget(btn, i // 2, i % 2)
            self.aio_buttons[name] = btn

        panel.addWidget(frame)

        # Power monitor
        btn_power = styled_button("Power Monitor", ACCENT_ORANGE, "⚡")
        btn_power.clicked.connect(lambda: launch_terminal("aiov2_ctl --power"))
        panel.addWidget(btn_power)

        return panel

    def _build_mesh_panel(self) -> QVBoxLayout:
        panel = QVBoxLayout()
        panel.setSpacing(4)

        panel.addWidget(section_label("📻 MESH RADIO", ACCENT_GREEN))

        frame = QFrame()
        frame.setStyleSheet(f"background-color: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; border-radius: 10px;")
        flay = QVBoxLayout(frame)
        flay.setSpacing(6)
        flay.setContentsMargins(8, 8, 8, 8)

        btn_mt = styled_button("Meshtastic", ACCENT_GREEN, "📡")
        btn_mt.clicked.connect(lambda: self._set_mesh("meshtastic"))
        flay.addWidget(btn_mt)

        btn_mc = styled_button("MeshCore", ACCENT_PURPLE, "🌐")
        btn_mc.clicked.connect(lambda: self._set_mesh("meshcore"))
        flay.addWidget(btn_mc)

        btn_off = styled_button("Mesh Off", ACCENT_RED, "⏻")
        btn_off.clicked.connect(lambda: self._set_mesh("off"))
        flay.addWidget(btn_off)

        panel.addWidget(frame)

        btn_contact = styled_button("Contact (TUI)", ACCENT_GREEN, "💬")
        btn_contact.clicked.connect(self._launch_contact)
        panel.addWidget(btn_contact)

        btn_meshdash = styled_button("MeshDash", ACCENT_CYAN, "📊")
        btn_meshdash.clicked.connect(lambda: launch_browser("http://localhost:8000"))
        panel.addWidget(btn_meshdash)

        return panel

    def _build_sdr_panel(self) -> QVBoxLayout:
        panel = QVBoxLayout()
        panel.setSpacing(4)

        panel.addWidget(section_label("📡 SDR / SIGINT", ACCENT_ORANGE))

        frame = QFrame()
        frame.setStyleSheet(f"background-color: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; border-radius: 10px;")
        flay = QVBoxLayout(frame)
        flay.setSpacing(6)
        flay.setContentsMargins(8, 8, 8, 8)

        btn_intercept = styled_button("iNTERCEPT", ACCENT_ORANGE, "🛰")
        btn_intercept.clicked.connect(self._launch_intercept)
        flay.addWidget(btn_intercept)

        btn_sdrpp = styled_button("SDR++", ACCENT_CYAN, "🎵")
        btn_sdrpp.clicked.connect(lambda: launch("sdrpp-brown 2>/dev/null &") if shutil_which("sdrpp-brown") else launch("sdrpp 2>/dev/null &"))
        flay.addWidget(btn_sdrpp)

        btn_tar1090 = styled_button("tar1090 (ADS-B)", ACCENT_GREEN, "✈")
        btn_tar1090.clicked.connect(self._launch_tar1090)
        flay.addWidget(btn_tar1090)

        panel.addWidget(frame)

        return panel

    def _build_system_panel(self) -> QVBoxLayout:
        panel = QVBoxLayout()
        panel.setSpacing(4)

        panel.addWidget(section_label("🖥 SYSTEM", ACCENT_PURPLE))

        frame = QFrame()
        frame.setStyleSheet(f"background-color: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; border-radius: 10px;")
        flay = QVBoxLayout(frame)
        flay.setSpacing(6)
        flay.setContentsMargins(8, 8, 8, 8)

        btn_gps = styled_button("PyGPSClient", ACCENT_GREEN, "📍")
        btn_gps.clicked.connect(lambda: launch("pygpsclient 2>/dev/null &"))
        flay.addWidget(btn_gps)

        btn_rtc = styled_button("Sync RTC", ACCENT_CYAN, "🕐")
        btn_rtc.clicked.connect(self._sync_rtc)
        flay.addWidget(btn_rtc)

        btn_terminal = styled_button("Terminal", TEXT_PRIMARY, "⌘")
        btn_terminal.clicked.connect(lambda: launch_terminal())
        flay.addWidget(btn_terminal)

        panel.addWidget(frame)

        btn_doctor = styled_button("Diagnostics", ACCENT_ORANGE, "🔧")
        btn_doctor.clicked.connect(lambda: launch_terminal("uconsole-doctor"))
        panel.addWidget(btn_doctor)

        return panel

    def _build_bottom_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)

        btn_reboot = styled_button("Reboot", ACCENT_ORANGE, "⟳")
        btn_reboot.setFixedHeight(48)
        btn_reboot.clicked.connect(lambda: launch("sudo reboot"))
        bar.addWidget(btn_reboot)

        btn_shutdown = styled_button("Shutdown", ACCENT_RED, "⏼")
        btn_shutdown.setFixedHeight(48)
        btn_shutdown.clicked.connect(lambda: launch("sudo shutdown -h now"))
        bar.addWidget(btn_shutdown)

        bar.addStretch()

        btn_exit = styled_button("Exit to Desktop →", ACCENT_CYAN, "▣")
        btn_exit.setFixedHeight(48)
        btn_exit.clicked.connect(self.close)
        bar.addWidget(btn_exit)

        return bar

    # ---- Actions ----

    def _toggle_aio(self, name: str) -> None:
        current = self.aio_states.get(name, False)
        action = "off" if current else "on"
        sudo_sh(f"aiov2_ctl {name} {action}")
        if shutil_which("pinctrl") and not shutil_which("aiov2_ctl"):
            pin_map = {"GPS": 27, "LORA": 16, "SDR": 7, "USB": 23}
            pin = pin_map.get(name)
            if pin:
                sudo_sh(f"pinctrl set {pin} op {'dh' if action == 'on' else 'dl'}")
        time.sleep(0.3)
        self._refresh_aio()

    def _set_mesh(self, mode: str) -> None:
        sudo_sh(f"uconsole-radio {mode}")
        time.sleep(1)
        self._refresh_mesh()

    def _launch_contact(self) -> None:
        if shutil_which("contact"):
            launch_terminal("contact --port /dev/ttyUSB0")
        else:
            launch_terminal("pipx install contact && contact --port /dev/ttyUSB0")

    def _launch_intercept(self) -> None:
        intercept_dir = "/opt/intercept"
        if Path(intercept_dir).exists():
            launch(f"cd {intercept_dir} && sudo ./start.sh &")
            time.sleep(2)
            launch_browser("http://localhost:5050")
        else:
            launch_terminal("echo 'iNTERCEPT not installed. Clone from github.com/smittix/intercept'")

    def _launch_tar1090(self) -> None:
        # tar1090 runs on localhost:8080 by default via readsb
        if sh("systemctl is-active readsb 2>/dev/null") != "active":
            sudo_sh("systemctl start readsb 2>/dev/null")
        launch_browser("http://localhost/tar1090")

    def _sync_rtc(self) -> None:
        launch_terminal("sudo aiov2_ctl --sync-rtc")

    # ---- Timers / refresh ----

    def _start_timers(self) -> None:
        self._refresh_status()
        self._refresh_aio()
        self._refresh_mesh()

        self.timer_status = QTimer()
        self.timer_status.timeout.connect(self._refresh_status)
        self.timer_status.start(2000)

        self.timer_aio = QTimer()
        self.timer_aio.timeout.connect(self._refresh_aio)
        self.timer_aio.start(3000)

        self.timer_mesh = QTimer()
        self.timer_mesh.timeout.connect(self._refresh_mesh)
        self.timer_mesh.start(5000)

    def _refresh_status(self) -> None:
        bat = get_battery()
        ac = get_ac_online()

        bat_color = ACCENT_GREEN if bat["capacity"] != "?" and int(bat["capacity"]) > 30 else ACCENT_RED
        if ac:
            bat_color = ACCENT_CYAN

        self.lbl_battery.setText(f"BAT {bat['capacity']}%")
        self.lbl_battery.setStyleSheet(f"""
            background-color: {bat_color}20; color: {bat_color};
            border: 1px solid {bat_color}60; border-radius: 12px; padding: 3px 10px;
        """)

        self.lbl_power.setText(f"⚡ {bat['power']}")
        self.lbl_power.setStyleSheet(f"""
            background-color: {ACCENT_ORANGE}20; color: {ACCENT_ORANGE};
            border: 1px solid {ACCENT_ORANGE}60; border-radius: 12px; padding: 3px 10px;
        """)

        wifi = get_wifi_info()
        self.lbl_wifi.setText(f"WiFi {wifi['ssid']}")
        self.lbl_ip.setText(f"IP {wifi['ip']}")

        self.lbl_clock.setText(time.strftime("%H:%M:%S"))

    def _refresh_aio(self) -> None:
        if self._building_toggles:
            return
        self._building_toggles = True
        new_states = get_aio_state()
        self.aio_states = new_states

        for name, btn in self.aio_buttons.items():
            is_on = new_states.get(name, False)
            color = ACCENT_GREEN if is_on else ACCENT_RED
            state_text = "ON" if is_on else "OFF"
            btn.blockSignals(True)
            btn.setText(f"{name}\n{state_text}")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color}18;
                    color: {color};
                    border: 2px solid {color};
                    border-radius: 10px;
                    text-align: center;
                }}
                QPushButton:hover {{ background-color: {color}30; }}
            """)
            btn.blockSignals(False)

        self._building_toggles = False

    def _refresh_mesh(self) -> None:
        mode = get_mesh_mode()
        self.mesh_mode = mode
        color = ACCENT_GREEN if mode == "Meshtastic" else ACCENT_PURPLE if mode == "MeshCore" else ACCENT_RED
        self.lbl_mesh.setText(f"MESH {mode}")
        self.lbl_mesh.setStyleSheet(f"""
            background-color: {color}20; color: {color};
            border: 1px solid {color}60; border-radius: 12px; padding: 3px 10px;
        """)

    # ---- Key handling ----

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("uConsole Field Launcher")

    # Dark palette as fallback
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(DARK_BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_PRIMARY))
    app.setPalette(pal)

    win = FieldLauncher()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
