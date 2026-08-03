#!/usr/bin/env python3
"""
RF-Deck — clean modern TUI launcher for the uConsole CM5.

Textual-based, dark theme, mouse + keyboard input.
No pixel art. No marine tab. Just a launcher.
Runs in any terminal — works over SSH too.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Header, Footer, Button, Label, Static, DataTable,
    TabbedContent, TabPane, RichLog,
)
from textual.binding import Binding
from textual.reactive import reactive
from textual import on


# ---------------------------------------------------------------------------
# Shell helpers
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
# Status readers
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
        info["ssid"] = ssid[:18]
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
    mode_file = Path("/tmp/sdr-mode-current")
    if mode_file.exists():
        mode = sh(f"cat {mode_file}")
        if mode:
            return mode.capitalize()
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
# CSS
# ---------------------------------------------------------------------------
CSS = """
Screen {
    background: #0a0e1a;
    color: #c8d0e0;
}

#status-bar {
    dock: top;
    height: 3;
    background: #0d1320;
    border-bottom: solid #2a3550;
    padding: 0 1;
    layout: horizontal;
}

.status-item {
    width: auto;
    min-width: 12;
    height: 3;
    padding: 0 1;
    content-align: center middle;
}

.status-label {
    color: #506070;
    text-style: bold;
    margin-right: 1;
}

.status-value {
    text-style: bold;
}

.status-ok    { color: #00c070; }
.status-warn  { color: #e08020; }
.status-err   { color: #e03050; }
.status-info  { color: #00b0d0; }
.status-off   { color: #506070; }

#main-area {
    layout: horizontal;
    height: 1fr;
}

#sidebar {
    width: 28;
    background: #0d1320;
    border-right: solid #2a3550;
    padding: 1 0;
}

.nav-btn {
    width: 100%;
    height: 3;
    margin: 0 1 0 0;
    border: none;
    background: transparent;
    color: #506070;
    text-align: left;
    padding: 0 1;
}

.nav-btn:hover {
    background: #1a2238;
    color: #c8d0e0;
}

.nav-btn.-active {
    background: #1a2238;
    color: #00b0d0;
    border-left: thick #00b0d0;
}

#content {
    width: 1fr;
    padding: 1 2;
    overflow-y: auto;
}

.page-title {
    color: #00b0d0;
    text-style: bold;
    margin-bottom: 1;
    width: 100%;
}

.section-title {
    color: #00b0d0;
    text-style: bold;
    margin-top: 1;
    margin-bottom: 0;
    width: 100%;
}

.app-btn {
    width: 1fr;
    height: 3;
    margin: 0 1 1 0;
    background: #141b2e;
    color: #c8d0e0;
    border: solid #2a3550;
    text-align: left;
    padding: 0 1;
}

.app-btn:hover {
    background: #1a2238;
    border: solid #00b0d0;
    color: #00b0d0;
}

.app-btn.-pressing {
    background: #00b0d0;
    color: #0a0e1a;
}

.btn-grid {
    layout: grid;
    grid-size: 2;
    grid-gutter: 1;
    width: 100%;
    margin-top: 0;
}

.aio-grid {
    layout: grid;
    grid-size: 4;
    grid-gutter: 1;
    width: 100%;
    margin-top: 1;
}

.aio-btn {
    height: 3;
    background: #141b2e;
    border: solid #2a3550;
    text-align: center;
    padding: 0;
}

.aio-btn.on  { color: #00c070; border: solid #00c07080; background: #00c07018; }
.aio-btn.off { color: #e03050; border: solid #e0305080; background: #e0305018; }
.aio-btn:hover { background: #1a2238; }

.info-panel {
    background: #141b2e;
    border: solid #2a3550;
    padding: 1 2;
    margin: 1 0;
    width: 100%;
}

.info-line {
    color: #506070;
    height: 1;
}

#log-panel {
    dock: bottom;
    height: 8;
    background: #0d1320;
    border-top: solid #2a3550;
    padding: 0 1;
}

#log-title {
    color: #00b0d0;
    text-style: bold;
    height: 1;
    margin-bottom: 0;
}

#log-content {
    height: 1fr;
    overflow-y: auto;
    color: #506070;
}

.log-err { color: #e03050; }
.log-ok  { color: #00c070; }
.log-sdr { color: #00b0d0; }
.log-mesh { color: #9040d0; }
.log-aio { color: #e08020; }
.log-sys { color: #506070; }
"""


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
PAGES = ["Dashboard", "SDR", "Mesh", "System"]


class RFDeckApp(App):
    CSS = CSS
    TITLE = "RF-Deck"
    BINDINGS = [
        Binding("1", "switch_page(0)", "Dashboard", show=True),
        Binding("2", "switch_page(1)", "SDR", show=True),
        Binding("3", "switch_page(2)", "Mesh", show=True),
        Binding("4", "switch_page(3)", "System", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    page = reactive(0)
    aio_states = reactive({})
    battery = reactive({})
    wifi = reactive({})
    mesh_mode = reactive("Off")
    sdr_mode = reactive("Off")
    gps_on = reactive(False)
    kb_backlight = reactive(False)
    event_log = reactive([])

    def __init__(self):
        super().__init__()
        self._log_lines = []

    def compose(self) -> ComposeResult:
        # Status bar
        with Horizontal(id="status-bar"):
            yield Label("RF-DECK", id="title-label",
                       classes="status-item status-info")
            yield Label("", id="s-bat", classes="status-item")
            yield Label("", id="s-pwr", classes="status-item")
            yield Label("", id="s-gps", classes="status-item")
            yield Label("", id="s-sdr", classes="status-item")
            yield Label("", id="s-mesh", classes="status-item")
            yield Label("", id="s-wifi", classes="status-item")
            yield Label("", id="s-clock", classes="status-item")

        # Main area: sidebar + content
        with Horizontal(id="main-area"):
            with Vertical(id="sidebar"):
                for i, name in enumerate(PAGES):
                    yield Button(f" {i+1}  {name}", id=f"nav-{i}",
                               classes="nav-btn")
            with Vertical(id="content"):
                yield Label("", id="page-content")

        # Log panel
        with Vertical(id="log-panel"):
            yield Label("> EVENT LOG", id="log-title")
            yield RichLog(id="log-content", markup=True, auto_scroll=True)

    def on_mount(self) -> None:
        self._refresh_all()
        self.set_interval(3, self._refresh_status)
        self.set_interval(4, self._refresh_aio)
        self.page = 0
        self._log("SYS", "RF-Deck online — ready.")

    # ---- Logging ----
    def _log(self, tag, msg):
        ts = time.strftime("%H:%M:%S")
        line = f"[dim]{ts}[/dim] [{tag}] {msg}"
        css_class = {
            "ERR": "log-err", "OK": "log-ok", "SDR": "log-sdr",
            "MESH": "log-mesh", "AIO": "log-aio", "SYS": "log-sys",
        }.get(tag, "log-sys")
        # Use markup for coloring
        colored = f"[dim]{ts}[/dim] [{css_class}][{tag}][/] {msg}"
        try:
            log = self.query_one("#log-content", RichLog)
            log.write(colored)
        except Exception:
            pass
        self._log_lines.append(f"{ts} [{tag}] {msg}")

    # ---- Status refresh ----
    def _refresh_all(self):
        self._refresh_status()
        self._refresh_aio()

    def _refresh_status(self):
        self.battery = get_battery()
        self.wifi = get_wifi()
        self.mesh_mode = get_mesh_mode()
        self.sdr_mode = get_sdr_mode()
        self.gps_on = get_gps_status()
        self._update_status_bar()

    def _refresh_aio(self):
        self.aio_states = get_aio_state()
        self.kb_backlight = get_kb_backlight()
        self._update_status_bar()
        if self.page == 0:
            self._render_page()

    def _update_status_bar(self):
        bat = self.battery
        bc = "status-ok" if bat.get("capacity", "?") != "?" and int(bat["capacity"]) > 30 else "status-err"
        if bat.get("charging"):
            bc = "status-info"
        bat_txt = f"⚡{bat['capacity']}%" if bat.get("charging") else f"{bat['capacity']}%"
        self._set_label("s-bat", "BAT", bat_txt, bc)

        if bat.get("power", "?") != "?":
            self._set_label("s-pwr", "PWR", bat["power"], "status-warn")
        else:
            self._set_label("s-pwr", "PWR", "—", "status-off")

        gc = "status-ok" if self.gps_on else "status-err"
        self._set_label("s-gps", "GPS", "ON" if self.gps_on else "OFF", gc)

        sc = "status-info" if self.sdr_mode != "Off" else "status-off"
        self._set_label("s-sdr", "SDR", self.sdr_mode[:10], sc)

        mc = "status-ok" if self.mesh_mode == "Meshtastic" else "status-info" if self.mesh_mode == "MeshCore" else "status-err"
        self._set_label("s-mesh", "MESH", self.mesh_mode[:8], mc)

        self._set_label("s-wifi", "WiFi", self.wifi["ssid"][:14], "status-info")
        self._set_label("s-clock", "", time.strftime("%H:%M"), "status-info")

    def _set_label(self, widget_id, label, value, css_class):
        try:
            w = self.query_one(f"#{widget_id}", Label)
            if label:
                w.update(f"[dim]{label}[/dim] [{css_class}]{value}[/]")
            else:
                w.update(f"[{css_class}]{value}[/]")
        except Exception:
            pass

    # ---- Page rendering ----
    def watch_page(self, page):
        for i in range(len(PAGES)):
            try:
                btn = self.query_one(f"#nav-{i}", Button)
                if i == page:
                    btn.add_class("-active")
                else:
                    btn.remove_class("-active")
            except Exception:
                pass
        self._render_page()

    def _render_page(self):
        try:
            content = self.query_one("#page-content", Label)
        except Exception:
            return

        if self.page == 0:
            content.update(self._render_dashboard())
        elif self.page == 1:
            content.update(self._render_sdr())
        elif self.page == 2:
            content.update(self._render_mesh())
        elif self.page == 3:
            content.update(self._render_system())

    def _render_dashboard(self):
        lines = []
        lines.append("[bold cyan]Dashboard[/]")
        lines.append("")
        lines.append("[bold cyan]Quick Launch[/]")
        lines.append("  1 iNTERCEPT   2 SDR++      3 WSJT-X     4 Terminal")
        lines.append("  5 GPS Client  6 AIO Tray")
        lines.append("")
        lines.append("[bold cyan]AIO Modules[/]")
        for name in ["GPS", "SDR", "USB", "LORA"]:
            on = self.aio_states.get(name, False)
            col = "green" if on else "red"
            icon = "●" if on else "○"
            lines.append(f"  [{col}]{icon} {name}[/]")
        lines.append("")
        lines.append("[bold cyan]System[/]")
        lines.append(f"  Mesh: [{self._mesh_color()}]{self.mesh_mode}[/]")
        lines.append(f"  SDR:  [{self._sdr_color()}]{self.sdr_mode}[/]")
        lines.append(f"  GPS:  [{'green' if self.gps_on else 'red'}]{'ON' if self.gps_on else 'OFF'}[/]")
        lines.append(f"  WiFi: [cyan]{self.wifi['ssid']}[/]")
        lines.append(f"  Bat:  [yellow]{self.battery['capacity']}%[/]  PWR: [orange]{self.battery['power']}[/]")
        return "\n".join(lines)

    def _render_sdr(self):
        lines = []
        lines.append("[bold cyan]SDR Tools[/]")
        lines.append("")
        lines.append("  1 iNTERCEPT       2 iNTERCEPT Web")
        lines.append("  3 SDR++           4 tar1090 (ADS-B)")
        lines.append("  5 WSJT-X (FT8)    6 rtl_433 Scan")
        lines.append("")
        lines.append("[bold cyan]SDR Mode[/]")
        col = "green" if self.sdr_mode != "Off" else "dim"
        lines.append(f"  [{col}]{self.sdr_mode}[/]")
        lines.append("")
        lines.append("[dim]One RTL-SDR = one decode at a time.")
        lines.append("Use iNTERCEPT web UI to switch modes.[/]")
        return "\n".join(lines)

    def _render_mesh(self):
        lines = []
        lines.append("[bold cyan]Mesh Control[/]")
        lines.append("")
        lines.append("  1 Meshtastic      2 MeshCore       3 Mesh Off")
        lines.append("  4 Contact TUI    5 MeshCore TUI   6 MeshDash Web")
        lines.append("")
        lines.append("[bold cyan]Mesh Mode[/]")
        col = self._mesh_color()
        lines.append(f"  [{col}]{self.mesh_mode}[/]")
        lines.append("")
        lines.append("[dim]Meshtastic and MeshCore share one SX1262.")
        lines.append("Switching stops the inactive stack first.[/]")
        return "\n".join(lines)

    def _render_system(self):
        lines = []
        lines.append("[bold cyan]System[/]")
        lines.append("")
        lines.append("  1 GPS Toggle      2 KB Backlight")
        lines.append("  3 Diagnostics     4 Terminal")
        lines.append("  5 Reboot          6 Shutdown")
        lines.append("")
        lines.append("[bold cyan]Status[/]")
        lines.append(f"  KB Backlight: [{'yellow' if self.kb_backlight else 'red'}]{'ON' if self.kb_backlight else 'OFF'}[/]")
        lines.append(f"  GPS:          [{'green' if self.gps_on else 'red'}]{'ON' if self.gps_on else 'OFF'}[/]")
        lines.append(f"  WiFi:         [cyan]{self.wifi['ssid']}[/]  IP: [dim]{self.wifi['ip']}[/]")
        return "\n".join(lines)

    def _mesh_color(self):
        if self.mesh_mode == "Meshtastic": return "green"
        if self.mesh_mode == "MeshCore": return "purple"
        return "red"

    def _sdr_color(self):
        return "green" if self.sdr_mode != "Off" else "dim"

    # ---- Actions ----
    def _act_intercept(self):
        if Path("/opt/intercept/start.sh").exists():
            launch("cd /opt/intercept && sudo ./start.sh")
            time.sleep(2)
            launch_browser("http://localhost:5050")
            self._log("SDR", "iNTERCEPT started + web launched")
        else:
            self._log("ERR", "iNTERCEPT not installed")

    def _act_intercept_web(self):
        launch_browser("http://localhost:5050")
        self._log("SDR", "iNTERCEPT web UI opened")

    def _act_sdrpp(self):
        if which("sdrpp-brown"):
            launch("sdrpp-brown &")
            self._log("SDR", "SDR++ launched")
        elif which("sdrpp"):
            launch("sdrpp &")
            self._log("SDR", "SDR++ launched")
        else:
            self._log("ERR", "SDR++ not installed")

    def _act_tar1090(self):
        if sh("systemctl is-active readsb 2>/dev/null") != "active":
            sudo_sh("systemctl start readsb 2>/dev/null")
        launch_browser("http://localhost/tar1090")
        self._log("SDR", "tar1090 ADS-B opened")

    def _act_wsjtx(self):
        if which("wsjtx"):
            launch("wsjtx &")
            self._log("SDR", "WSJT-X launched")
        else:
            self._log("ERR", "WSJT-X not installed")

    def _act_rtl433(self):
        launch_terminal("rtl_433 -G 2>&1 | head -100")
        self._log("SDR", "rtl_433 scanning...")

    def _act_terminal(self):
        launch_terminal()
        self._log("SYS", "Terminal opened")

    def _act_gpsclient(self):
        launch("pygpsclient 2>/dev/null &")
        self._log("SYS", "PyGPSClient launched")

    def _act_aiotray(self):
        launch("aiov2_ctl --gui 2>/dev/null &")
        self._log("SYS", "AIO tray GUI launched")

    def _act_mesh_mh(self):
        launch("sudo uconsole-radio meshtastic")
        self._log("MESH", "Switching to Meshtastic...")

    def _act_mesh_mc(self):
        launch("sudo uconsole-radio meshcore")
        self._log("MESH", "Switching to MeshCore...")

    def _act_mesh_off(self):
        launch("sudo uconsole-radio off")
        self._log("MESH", "Mesh radio off")

    def _act_contact(self):
        if which("contact"):
            launch_terminal("contact --port /dev/ttyUSB0")
        else:
            launch_terminal("pipx install contact && contact --port /dev/ttyUSB0")
        self._log("MESH", "Contact TUI")

    def _act_mctui(self):
        if which("tui-meshcore"):
            launch_terminal("tui-meshcore")
        else:
            launch_terminal("pipx install git+https://github.com/guax/tui-meshcore.git && tui-meshcore")
        self._log("MESH", "MeshCore TUI")

    def _act_meshdash(self):
        launch_browser("http://localhost:8000")
        self._log("MESH", "MeshDash web opened")

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
                self._log("SYS", f"KB backlight {'ON' if new != '0' else 'OFF'}")
                return

    def _act_diag(self):
        launch_terminal("uconsole-doctor")
        self._log("SYS", "Running diagnostics...")

    def _act_reboot(self):
        self._log("SYS", "Rebooting...")
        subprocess.run("sudo reboot", shell=True)

    def _act_shutdown(self):
        self._log("SYS", "Shutting down...")
        subprocess.run("sudo shutdown -h now", shell=True)

    def _toggle_aio(self, name):
        current = self.aio_states.get(name, False)
        action = "off" if current else "on"
        if which("aiov2_ctl"):
            sudo_sh(f"aiov2_ctl {name} {action}")
            self._log("AIO", f"{name} {action.upper()}")
        elif which("pinctrl"):
            pin_map = {"GPS": 27, "LORA": 16, "SDR": 7, "USB": 23}
            pin = pin_map.get(name)
            if pin:
                sudo_sh(f"pinctrl set {pin} op {'dh' if action == 'on' else 'dl'}")
                self._log("AIO", f"{name} {action.upper()}")
        time.sleep(0.3)
        self._refresh_aio()

    # ---- Input handlers ----
    def action_switch_page(self, idx):
        self.page = idx

    @on(Button.Pressed)
    def on_button(self, event):
        btn_id = event.button.id
        if btn_id and btn_id.startswith("nav-"):
            idx = int(btn_id.split("-")[1])
            self.page = idx
            return

        # Number key actions per page
        actions = {
            0: [  # Dashboard
                self._act_intercept, self._act_sdrpp, self._act_wsjtx,
                self._act_terminal, self._act_gpsclient, self._act_aiotray,
            ],
            1: [  # SDR
                self._act_intercept, self._act_intercept_web, self._act_sdrpp,
                self._act_tar1090, self._act_wsjtx, self._act_rtl433,
            ],
            2: [  # Mesh
                self._act_mesh_mh, self._act_mesh_mc, self._act_mesh_off,
                self._act_contact, self._act_mctui, self._act_meshdash,
            ],
            3: [  # System
                self._act_gps_toggle, self._act_kbd, self._act_diag,
                self._act_terminal, self._act_reboot, self._act_shutdown,
            ],
        }

        # Check for app button clicks (we use Button IDs for these)
        if btn_id and btn_id.startswith("app-"):
            idx = int(btn_id.split("-")[1])
            page_actions = actions.get(self.page, [])
            if idx < len(page_actions):
                page_actions[idx]()

    def on_key(self, event):
        # Number keys 1-6 trigger actions on current page
        if event.character and event.character in "123456":
            idx = int(event.character) - 1
            actions = {
                0: [self._act_intercept, self._act_sdrpp, self._act_wsjtx,
                     self._act_terminal, self._act_gpsclient, self._act_aiotray],
                1: [self._act_intercept, self._act_intercept_web, self._act_sdrpp,
                    self._act_tar1090, self._act_wsjtx, self._act_rtl433],
                2: [self._act_mesh_mh, self._act_mesh_mc, self._act_mesh_off,
                    self._act_contact, self._act_mctui, self._act_meshdash],
                3: [self._act_gps_toggle, self._act_kbd, self._act_diag,
                    self._act_terminal, self._act_reboot, self._act_shutdown],
            }
            page_actions = actions.get(self.page, [])
            if idx < len(page_actions):
                page_actions[idx]()
                event.prevent_default()


def main():
    app = RFDeckApp()
    app.run()


if __name__ == "__main__":
    main()
