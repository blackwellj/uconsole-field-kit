# uConsole Field Kit

An idempotent installer for a ClockworkPi uConsole CM5 fitted with:

* HackerGadgets AIO V2 (SX1262 LoRa, RTL-SDR, GPS, RTC, USB hub)
* NVMe storage board

Built on Rex's Debian 12 Bookworm (akrex kernel 6.12.67) image.

## One-command install

```bash
git clone https://github.com/blackwellj/uconsole-field-kit.git
cd uconsole-field-kit
sudo ./install.sh
```

That's it. The installer does everything and reboots the device. After reboot the Field Launcher appears automatically.

## What it installs

| Category | Software | Notes |
|----------|----------|-------|
| **AIO control** | aiov2_ctl | GPIO control + boot-rail service + GUI tray |
| **AIO apps** | sdrpp-brown, meshtastic-mui, tar1090, pygpsclient | via `aiov2_ctl --add-apps` |
| **Backlight** | clockworkpi-backlight | Panel + keyboard backlight control |
| **Mesh radio** | meshtasticd, meshtastic CLI, Contact TUI | `pipx install contact` |
| **Mesh radio** | MeshCore (cwill747) | Cloned + installed from GitHub |
| **Mesh dashboard** | MeshDash R3.1.2 | Web UI on port 8000 |
| **SIGINT** | iNTERCEPT (smittix) | Web UI on port 5050 |
| **SDR** | SDR++, tar1090 (ADS-B), rtl-433 | Preconfigured for uConsole |
| **Ham radio** | WSJT-X | FT8/FT4/JT modes |
| **GPS** | gpsd + PyGPSClient + chrony | Stratum-1 NTP server via GPS PPS |
| **Remote access** | SSH (port 22), VNC (port 5900) | VNC shares physical display |
| **Power** | Power button daemon | Short press = backlight toggle, long press = poweroff |
| **Launcher** | Field Launcher (PyQt6) | Fullscreen kiosk UI at boot, exit to desktop |

## Field Launcher

A fullscreen PyQt6 dark-themed launcher appears at boot. It provides:

* **AIO module toggles** — GPS, SDR, USB, LoRa (live on/off state)
* **Keyboard backlight** toggle
* **Mesh mode** — Meshtastic / MeshCore / Off (with status)
* **Apps** — iNTERCEPT, SDR++, tar1090, WSJT-X, Contact, MeshDash, PyGPSClient
* **System** — RTC sync, terminal, diagnostics, reboot, shutdown
* **Status bar** — Battery %, power draw, WiFi SSID, IP, mesh mode, VNC/SSH status, clock
* **Exit to Desktop** — reveals full XFCE desktop

Run `field-launcher` from a terminal to restart it.

## NVMe provisioning (optional, before install)

If you want to boot from NVMe instead of SD, run this first while booted from SD:

```bash
sudo ./provision-nvme.sh
```

It clones the SD card to the NVMe, expands the filesystem, configures the CM5 EEPROM boot order, and shuts down. Remove the SD card and power back on.

## Remote access

```bash
# SSH (enabled by default)
ssh <user>@<uconsole-ip>

# VNC (shares the physical display)
# Connect to <uconsole-ip>:5900
# Password is auto-generated — check /etc/x11vnc.pass
sudo cat /etc/x11vnc.pass
```

## Commands

```bash
uconsole-doctor              # system diagnostics
uconsole-radio status        # mesh status
uconsole-radio meshtastic    # switch to Meshtastic
uconsole-radio meshcore      # switch to MeshCore
uconsole-radio off           # stop all mesh
aiov2_ctl --status            # AIO board + battery
aiov2_ctl --power             # live power monitor
contact --port /dev/ttyUSB0   # Meshtastic TUI chat
field-launcher                # restart the launcher UI
```

## Web UIs

| Service | URL | Port |
|---------|-----|------|
| MeshDash | http://localhost:8000 | 8000 |
| iNTERCEPT | http://localhost:5050 | 5050 |
| tar1090 (ADS-B) | http://localhost/tar1090 | 80 |

## Notes

* Meshtastic and MeshCore cannot both own the AIO SX1262 simultaneously. `uconsole-radio` stops the inactive stack before starting the selected one. It controls the LoRa GPIO pin directly via `pinctrl` to avoid `aiov2_ctl`'s implicit meshtasticd auto-start.

* Boot-rail GPIO states are owned by `aiov2-rails-boot.service` from the upstream `aiov2_ctl` package. The field kit's `aio-boot.sh` configures per-rail preferences via `aiov2_ctl --boot-rail`.

* GPS NTP: gpsd reads the AIO GPS module on `/dev/ttyAMA0` and chrony uses it as a Stratum-1 time source via shared memory. Other devices on the network can sync time from the uConsole.

* VNC uses x11vnc which mirrors the physical display — you see exactly what's on the uConsole screen.

* The installer does not install CoastalHub.
