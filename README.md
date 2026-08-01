# uConsole Field Kit

An idempotent installer for a ClockworkPi uConsole CM5 fitted with:

* HackerGadgets AIO V2
* NVMe storage board
* SX1262 LoRa
* RTL SDR
* GPS
* Internal USB power switching

It provisions a blank NVMe by cloning the currently running, known good uConsole SD installation, expands the root filesystem, and then installs the requested software.

## Installed features

* HackerGadgets AIO controller and GUI (via `aiov2_ctl --install`)
* HackerGadgets AIO companion apps: `sdrpp-brown`, `meshtastic-mui`, `tar1090`, `pygpsclient`
* GPS, SDR and internal USB enabled at boot (configured through `aiov2_ctl --boot-rail`, applied by the upstream `aiov2-rails-boot.service`)
* LoRa power control
* Short power button press toggles the display backlight
* Meshtastic CLI
* Meshtastic native daemon when available from the configured APT repositories
* MeshCore uConsole software
* MeshDash
* A mesh mode switcher which prevents MeshCore and Meshtastic from fighting over the same SX1262
* SDR, GPS, networking and diagnostic tools
* Node RED
* `uconsole-doctor`
* `uconsole-radio`
* `uconsole-display`
* Hardware RTC sync (`aiov2_ctl --sync-rtc`)

## Important

The NVMe provisioning command erases the selected NVMe completely.

Run it while booted from a working uConsole SD card. Keep external power connected and remove the SD card only after shutdown.

## First stage: clone SD to NVMe

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/uconsole-field-kit.git
cd uconsole-field-kit
sudo ./provision-nvme.sh
```

The script detects the current root disk and the NVMe, prints both, and requires an exact confirmation before cloning.

After it shuts down:

1. Remove the SD card
2. Power the uConsole on
3. Confirm it booted from NVMe with:

```bash
findmnt -no SOURCE /
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
```

## Second stage: install the field kit

From the repository directory on the NVMe:

```bash
sudo ./install.sh
```

Reboot when it finishes:

```bash
sudo reboot
```

## Commands

```bash
uconsole-doctor
uconsole-radio status
uconsole-radio meshtastic
uconsole-radio meshcore
uconsole-radio off
uconsole-display toggle
aiov2_ctl --status
```

MeshDash is available at:

```text
http://localhost:8000/setup
```

or from another machine:

```text
http://UCONSOLE_IP:8000/setup
```

## Notes

Meshtastic and MeshCore cannot both own the AIO SX1262 simultaneously. `uconsole-radio` stops the inactive stack before starting the selected one. It controls the LoRa GPIO pin directly via `pinctrl` to avoid `aiov2_ctl`'s implicit meshtasticd auto-start, then manages the systemd services explicitly.

Boot-rail GPIO states (GPS, SDR, USB, LoRa power at boot) are owned by `aiov2-rails-boot.service` from the upstream `aiov2_ctl` package. The field kit's `aio-boot.sh` configures the per-rail preferences via `aiov2_ctl --boot-rail` during install; no duplicate boot service is installed.

MeshDash is a Meshtastic dashboard. It will only receive data while Meshtastic is active and configured.

The installer does not install CoastalHub.
