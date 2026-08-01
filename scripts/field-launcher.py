#!/usr/bin/env python3
"""
uConsole Field Launcher v2 — tabbed fullscreen PyQt6 kiosk UI.

Clean tabbed layout, visual click feedback, desktop icon, fast refresh.
Exit reveals full desktop.  Run 'field-launcher' to restart.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QLabel, QFrame, QSizePolicy,
    QStackedWidget, QTabWidget,
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
    if ssid:
        info["ssid"] = ssid[:12]
    ip = sh("ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1")
    if ip:
        info["ip"] = ip
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
    for path in (
        "/sys/class/leds/kbd_backlight/brightness",
        "/sys/class/leds/clockworkpi::kbd_backlight/brightness",
    ):
        if Path(path).exists():
            return int(sh(f"cat {path}") or "0") > 0
    return False

def get_vnc_status() -> str:
    return "ON" if sh("systemctl is-active x11vnc 2>/dev/null") == "active" else "OFF"

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

BG = "#0d0d12"
PANEL = "#1a1a26"
BORDER = "#303040"
CYAN = "#00b0d0"
GREEN = "#00c070"
RED = "#e03050"
ORANGE = "#e08020"
PURPLE = "#9040d0"
YELLOW = "#d0b000"
WHITE = "#d0d0e0"
DIM = "#505060"
FONT = "DejaVu Sans"

def make_btn(text: str, color: str = CYAN, h: int = 50, font_size: int = 11) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(h)
    btn.setFont(QFont(FONT, font_size, QFont.Weight.Bold))
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {PANEL};
            color: {color};
            border: 1px solid {color}60;
            border-radius: 6px;
            padding: 4px 10px;
        }}
        QPushButton:hover {{
            background-color: {color}25;
            border: 1px solid {color};
        }}
        QPushButton:pressed {{
            background-color: {color};
            color: {BG};
        }}
    """)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return btn

def make_toggle(text: str, is_on: bool) -> QPushButton:
    c = GREEN if is_on else RED
    btn = QPushButton(f"{text}\n{'ON' if is_on else 'OFF'}")
    btn.setFixedHeight(50)
    btn.setFont(QFont(FONT, 10, QFont.Weight.Bold))
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {c}20; color: {c};
            border: 2px solid {c}; border-radius: 6px; text-align: center;
        }}
        QPushButton:hover {{ background-color: {c}35; }}
        QPushButton:pressed {{ background-color: {c}; color: {BG}; }}
    """)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return btn

def make_status(text: str, color: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont(FONT, 8, QFont.Weight.Bold))
    lbl.setStyleSheet(f"background-color: {color}18; color: {color}; border: 1px solid {color}50; border-radius: 10px; padding: 2px 6px;")
    return lbl

def make_panel() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setStyleSheet(f"background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px;")
    lay = QVBoxLayout(frame)
    lay.setSpacing(5)
    lay.setContentsMargins(8, 8, 8, 8)
    return frame, lay

def make_section(text: str, color: str = DIM) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont(FONT, 8, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color: {color}; padding: 0 0 2px 2px;")
    return lbl

# ---------------------------------------------------------------------------
# Click feedback widget
# ---------------------------------------------------------------------------

class ClickButton(QPushButton):
    """Button that flashes green when clicked for visual feedback."""
    clicked_with_feedback = pyqtSignal(str)
    _flash_timer = None

    def __init__(self, text: str, color: str = CYAN, h: int = 50, font_size: int = 11):
        super().__init__(text)
        self._color = color
        self._orig_style = ""
        self.setFixedHeight(h)
        self.setFont(QFont(FONT, font_size, QFont.Weight.Bold))
        self._apply_style()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pressed.connect(self._on_press)
        self.released.connect(self._on_release)

    def _apply_style(self):
        c = self._color
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {PANEL}; color: {c};
                border: 1px solid {c}60; border-radius: 6px; padding: 4px 10px;
            }}
            QPushButton:hover {{ background-color: {c}25; border: 1px solid {c}; }}
            QPushButton:pressed {{ background-color: {c}; color: {BG}; }}
        """)

    def _on_press(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {GREEN}; color: {BG};
                border: 2px solid {GREEN}; border-radius: 6px; padding: 4px 10px;
            }}
        """)

    def _on_release(self):
        self._apply_style()
        # Brief flash
        QTimer.singleShot(50, lambda: None)

# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class FieldLauncher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("uConsole Field Launcher")
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
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 4, 8, 4)
        root.setSpacing(3)

        root.addLayout(self._build_status_bar())

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; background-color: {BG}; }}
            QTabBar::tab {{
                background-color: {PANEL}; color: {DIM};
                border: 1px solid {BORDER}; border-radius: 4px;
                padding: 6px 16px; margin-right: 4px; font-weight: bold;
                font-size: 10pt; font-family: {FONT};
            }}
            QTabBar::tab:selected {{ background-color: {PANEL}; color: {CYAN}; border: 1px solid {CYAN}; }}
            QTabBar::tab:hover {{ color: {WHITE}; }}
        """)

        self.tabs.addTab(self._build_tab_radio(), "Radio")
        self.tabs.addTab(self._build_tab_sdr(), "SDR")
        self.tabs.addTab(self._build_tab_system(), "System")
        root.addWidget(self.tabs, 1)
        root.addLayout(self._build_bottom_bar())

    # ---- Status bar ----

    def _build_status_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        title = QLabel("uCONSOLE")
        title.setFont(QFont(FONT, 10, QFont.Weight.Black))
        title.setStyleSheet(f"color: {CYAN}; letter-spacing: 1px;")
        bar.addWidget(title)

        bar.addStretch()

        self.lbl_bat = make_status("BAT ?%", GREEN)
        self.lbl_pwr = make_status("PWR ?", ORANGE)
        self.lbl_wifi = make_status("WiFi —", CYAN)
        self.lbl_ip = make_status("IP —", PURPLE)
        self.lbl_mesh = make_status("MESH Off", RED)
        self.lbl_vnc = make_status("VNC OFF", YELLOW)
        self.lbl_clk = make_status("--:--", DIM)

        for w in (self.lbl_bat, self.lbl_pwr, self.lbl_wifi, self.lbl_ip,
                 self.lbl_mesh, self.lbl_vnc, self.lbl_clk):
            bar.addWidget(w)

        return bar

    # ---- Radio tab ----

    def _build_tab_radio(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(6)
        lay.setContentsMargins(8, 8, 8, 8)

        # AIO toggles
        lay.addWidget(make_section("AIO V2 MODULES", CYAN))
        frame, flay = make_panel()
        grid = QGridLayout()
        grid.setSpacing(4)
        self.aio_buttons = {}
        for i, name in enumerate(["GPS", "SDR", "USB", "LORA"]):
            btn = make_toggle(name, False)
            btn.clicked.connect(lambda _, n=name: self._toggle_aio(n))
            grid.addWidget(btn, i // 2, i % 2)
            self.aio_buttons[name] = btn
        flay.addLayout(grid)
        lay.addWidget(frame)

        # Keyboard backlight
        self.btn_kbd = make_toggle("KBD BACKLIGHT", False)
        self.btn_kbd.clicked.connect(self._toggle_kbd)
        lay.addWidget(self.btn_kbd)

        # Mesh control
        lay.addWidget(make_section("MESH MODE", GREEN))
        frame2, flay2 = make_panel()
        row = QHBoxLayout()
        row.setSpacing(4)

        btn_mt = make_btn("Meshtastic", GREEN)
        btn_mt.clicked.connect(lambda: self._do_action("uconsole-radio meshtastic", "Switching to Meshtastic..."))
        row.addWidget(btn_mt)

        btn_mc = make_btn("MeshCore", PURPLE)
        btn_mc.clicked.connect(lambda: self._do_action("uconsole-radio meshcore", "Switching to MeshCore..."))
        row.addWidget(btn_mc)

        btn_off = make_btn("All Off", RED)
        btn_off.clicked.connect(lambda: self._do_action("uconsole-radio off", "Stopping mesh..."))
        row.addWidget(btn_off)

        flay2.addLayout(row)
        lay.addWidget(frame2)

        # Mesh apps
        lay.addWidget(make_section("MESH APPS", GREEN))
        frame3, flay3 = make_panel()
        row2 = QHBoxLayout()
        row2.setSpacing(4)

        btn_contact = make_btn("Contact (TUI)", GREEN)
        btn_contact.clicked.connect(self._launch_contact)
        row2.addWidget(btn_contact)

        btn_mc_tui = make_btn("MeshCore TUI", PURPLE)
        btn_mc_tui.clicked.connect(self._launch_mc_tui)
        row2.addWidget(btn_mc_tui)

        btn_dash = make_btn("MeshDash", CYAN)
        btn_dash.clicked.connect(lambda: launch_browser("http://localhost:8000"))
        row2.addWidget(btn_dash)

        flay3.addLayout(row2)
        lay.addWidget(frame3)

        lay.addStretch()
        return page

    # ---- SDR tab ----

    def _build_tab_sdr(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(6)
        lay.setContentsMargins(8, 8, 8, 8)

        lay.addWidget(make_section("SIGINT PLATFORM", ORANGE))
        frame, flay = make_panel()

        btn_intercept = make_btn("Start iNTERCEPT", ORANGE, h=60, font_size=12)
        btn_intercept.clicked.connect(self._launch_intercept)
        flay.addWidget(btn_intercept)

        btn_intercept_web = make_btn("Open iNTERCEPT Web UI", CYAN)
        btn_intercept_web.clicked.connect(lambda: launch_browser("http://localhost:5050"))
        flay.addWidget(btn_intercept_web)

        lay.addWidget(frame)

        lay.addWidget(make_section("SDR TOOLS", CYAN))
        frame2, flay2 = make_panel()

        row = QHBoxLayout()
        row.setSpacing(4)

        btn_sdrpp = make_btn("SDR++", CYAN)
        btn_sdrpp.clicked.connect(self._launch_sdrpp)
        row.addWidget(btn_sdrpp)

        btn_tar = make_btn("tar1090", GREEN)
        btn_tar.clicked.connect(self._launch_tar1090)
        row.addWidget(btn_tar)

        flay2.addLayout(row)

        btn_wsjtx = make_btn("WSJT-X", YELLOW)
        btn_wsjtx.clicked.connect(self._launch_wsjtx)
        flay2.addWidget(btn_wsjtx)

        lay.addWidget(frame2)

        lay.addWidget(make_section("POWER MONITOR", ORANGE))
        frame3, flay3 = make_panel()
        btn_pwr = make_btn("Live Power Monitor", ORANGE)
        btn_pwr.clicked.connect(lambda: launch_terminal("aiov2_ctl --power"))
        flay3.addWidget(btn_pwr)
        lay.addWidget(frame3)

        lay.addStretch()
        return page

    # ---- System tab ----

    def _build_tab_system(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(6)
        lay.setContentsMargins(8, 8, 8, 8)

        lay.addWidget(make_section("GPS & TIME", GREEN))
        frame, flay = make_panel()
        row = QHBoxLayout()
        row.setSpacing(4)

        btn_gps = make_btn("PyGPSClient", GREEN)
        btn_gps.clicked.connect(lambda: launch("pygpsclient 2>/dev/null &"))
        row.addWidget(btn_gps)

        btn_rtc = make_btn("Sync RTC", CYAN)
        btn_rtc.clicked.connect(self._sync_rtc)
        row.addWidget(btn_rtc)

        flay.addLayout(row)
        lay.addWidget(frame)

        lay.addWidget(make_section("DIAGNOSTICS", ORANGE))
        frame2, flay2 = make_panel()
        btn_doc = make_btn("Run Diagnostics", ORANGE)
        btn_doc.clicked.connect(lambda: launch_terminal("uconsole-doctor"))
        flay2.addWidget(btn_doc)
        lay.addWidget(frame2)

        lay.addWidget(make_section("TOOLS", WHITE))
        frame3, flay3 = make_panel()
        row3 = QHBoxLayout()
        row3.setSpacing(4)

        btn_term = make_btn("Terminal", WHITE)
        btn_term.clicked.connect(lambda: launch_terminal())
        row3.addWidget(btn_term)

        btn_aio_gui = make_btn("AIO Tray GUI", CYAN)
        btn_aio_gui.clicked.connect(lambda: launch("aiov2_ctl --gui 2>/dev/null &"))
        row3.addWidget(btn_aio_gui)

        flay3.addLayout(row3)
        lay.addWidget(frame3)

        lay.addStretch()
        return page

    # ---- Bottom bar ----

    def _build_bottom_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        btn_reboot = make_btn("Reboot", ORANGE, h=40, font_size=10)
        btn_reboot.clicked.connect(lambda: subprocess.run("sudo reboot", shell=True))
        bar.addWidget(btn_reboot)

        btn_shutdown = make_btn("Shutdown", RED, h=40, font_size=10)
        btn_shutdown.clicked.connect(lambda: subprocess.run("sudo shutdown -h now", shell=True))
        bar.addWidget(btn_shutdown)

        bar.addStretch()

        btn_exit = make_btn("Exit to Desktop", CYAN, h=40, font_size=10)
        btn_exit.clicked.connect(self.close)
        bar.addWidget(btn_exit)

        return bar

    # ---- Actions ----

    def _do_action(self, cmd: str, msg: str = "") -> None:
        """Run a sudo command with visual feedback."""
        launch(f"sudo {cmd}")
        if msg:
            self.statusBar().showMessage(msg, 2000)
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
        for path in (
            "/sys/class/leds/kbd_backlight/brightness",
            "/sys/class/leds/clockworkpi::kbd_backlight/brightness",
        ):
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
        self.timer_kbd.start(3000)

    def _refresh_status(self) -> None:
        bat = get_battery()
        ac = get_ac()
        bc = GREEN if bat["capacity"] != "?" and int(bat["capacity"]) > 30 else RED
        if ac:
            bc = CYAN
        self.lbl_bat.setText(f"BAT {bat['capacity']}%")
        self.lbl_bat.setStyleSheet(f"background-color: {bc}18; color: {bc}; border: 1px solid {bc}50; border-radius: 10px; padding: 2px 6px;")
        self.lbl_pwr.setText(f"PWR {bat['power']}")
        wifi = get_wifi()
        self.lbl_wifi.setText(f"WiFi {wifi['ssid']}")
        self.lbl_ip.setText(f"IP {wifi['ip']}")
        self.lbl_clk.setText(time.strftime("%H:%M"))
        mode = get_mesh_mode()
        mc = GREEN if mode == "Meshtastic" else PURPLE if mode == "MeshCore" else RED
        self.lbl_mesh.setText(f"MESH {mode}")
        self.lbl_mesh.setStyleSheet(f"background-color: {mc}18; color: {mc}; border: 1px solid {mc}50; border-radius: 10px; padding: 2px 6px;")
        vnc = get_vnc_status()
        vc = GREEN if vnc == "ON" else RED
        self.lbl_vnc.setText(f"VNC {vnc}")
        self.lbl_vnc.setStyleSheet(f"background-color: {vc}18; color: {vc}; border: 1px solid {vc}50; border-radius: 10px; padding: 2px 6px;")

    def _refresh_aio(self) -> None:
        if self._building:
            return
        self._building = True
        new = get_aio_state()
        self.aio_states = new
        for name, btn in self.aio_buttons.items():
            is_on = new.get(name, False)
            c = GREEN if is_on else RED
            btn.blockSignals(True)
            btn.setText(f"{name}\n{'ON' if is_on else 'OFF'}")
            btn.setStyleSheet(f"QPushButton {{ background-color: {c}20; color: {c}; border: 2px solid {c}; border-radius: 6px; text-align: center; }} QPushButton:hover {{ background-color: {c}35; }} QPushButton:pressed {{ background-color: {c}; color: {BG}; }}")
            btn.blockSignals(False)
        self._building = False

    def _refresh_kbd(self) -> None:
        is_on = get_kb_backlight()
        c = YELLOW if is_on else RED
        self.btn_kbd.blockSignals(True)
        self.btn_kbd.setText(f"KBD BACKLIGHT\n{'ON' if is_on else 'OFF'}")
        self.btn_kbd.setStyleSheet(f"QPushButton {{ background-color: {c}20; color: {c}; border: 2px solid {c}; border-radius: 6px; text-align: center; }} QPushButton:hover {{ background-color: {c}35; }} QPushButton:pressed {{ background-color: {c}; color: {BG}; }}")
        self.btn_kbd.blockSignals(False)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("uConsole Field Launcher")
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(WHITE))
    app.setPalette(pal)
    win = FieldLauncher()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
