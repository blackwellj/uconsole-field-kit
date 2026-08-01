#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/common.sh"
need_root

TARGET="${1:-/dev/nvme0n1}"
[[ -b "$TARGET" ]] || die "NVMe target $TARGET does not exist."

ROOT_SOURCE="$(findmnt -no SOURCE /)"
ROOT_PART="$(readlink -f "$ROOT_SOURCE")"
PKNAME="$(lsblk -no PKNAME "$ROOT_PART" | head -n1)"
[[ -n "$PKNAME" ]] || die "Could not determine the current root disk."
SOURCE="/dev/$PKNAME"

[[ "$SOURCE" != "$TARGET" ]] || die "The system is already running from $TARGET."
[[ "$SOURCE" == /dev/mmcblk* || "$SOURCE" == /dev/sd* ]] || die "Expected to be booted from SD or USB, but root disk is $SOURCE."
[[ "$TARGET" == /dev/nvme* ]] || die "Target is not an NVMe device."

SOURCE_SIZE="$(blockdev --getsize64 "$SOURCE")"
TARGET_SIZE="$(blockdev --getsize64 "$TARGET")"
(( TARGET_SIZE >= SOURCE_SIZE )) || die "The NVMe is smaller than the source disk."

log "Current root partition: $ROOT_PART"
log "Source disk: $SOURCE"
lsblk -o NAME,MODEL,SIZE,TYPE,FSTYPE,MOUNTPOINTS "$SOURCE" | tee -a "$LOG_FILE"
log "Target disk: $TARGET"
lsblk -o NAME,MODEL,SIZE,TYPE,FSTYPE,MOUNTPOINTS "$TARGET" | tee -a "$LOG_FILE"

echo
echo "THIS WILL ERASE ALL DATA ON $TARGET"
echo "It will clone the complete current uConsole SD installation to the NVMe."
echo
read -r -p "Type the exact target path '$TARGET' to continue: " confirmation
[[ "$confirmation" == "$TARGET" ]] || die "Confirmation did not match."

while read -r mountpoint; do
    [[ -z "$mountpoint" ]] || umount "$mountpoint"
done < <(lsblk -lnpo MOUNTPOINTS "$TARGET" | awk 'NF' | sort -r)

log "Cloning $SOURCE to $TARGET. Do not interrupt power."
dd if="$SOURCE" of="$TARGET" bs=16M iflag=fullblock oflag=direct conv=fsync status=progress
sync

log "Repairing the backup GPT and rereading the partition table."
if command_exists sgdisk; then
    sgdisk -e "$TARGET"
fi
partprobe "$TARGET" || true
udevadm settle

LAST_PART_NUM="$(lsblk -lnpo NAME,TYPE "$TARGET" | awk '$2=="part"{print $1}' | sed -E 's/.*p?([0-9]+)$/\1/' | tail -n1)"
[[ -n "$LAST_PART_NUM" ]] || die "No partitions found on cloned NVMe."

if ! command_exists growpart; then
    apt-get update
    apt_install cloud-guest-utils
fi

log "Expanding partition $LAST_PART_NUM to fill the NVMe."
growpart "$TARGET" "$LAST_PART_NUM" || true
partprobe "$TARGET" || true
udevadm settle

if [[ "$TARGET" == *[0-9] ]]; then
    LAST_PART="${TARGET}p${LAST_PART_NUM}"
else
    LAST_PART="${TARGET}${LAST_PART_NUM}"
fi

FSTYPE="$(blkid -o value -s TYPE "$LAST_PART" || true)"
case "$FSTYPE" in
    ext2|ext3|ext4)
        e2fsck -pf "$LAST_PART" || [[ $? -le 1 ]]
        resize2fs "$LAST_PART"
        ;;
    btrfs)
        log "Btrfs detected. It will be expanded after first boot."
        ;;
    *)
        log "Root filesystem type is $FSTYPE. Automatic filesystem expansion was not attempted."
        ;;
esac

if command_exists rpi-eeprom-config; then
    EEPROM_BACKUP="/root/uconsole-eeprom-config-$(date +%Y%m%d-%H%M%S).txt"
    rpi-eeprom-config > "$EEPROM_BACKUP"
    log "EEPROM configuration backed up to $EEPROM_BACKUP"

    TMP_CONFIG="$(mktemp)"
    rpi-eeprom-config > "$TMP_CONFIG"
    if grep -q '^BOOT_ORDER=' "$TMP_CONFIG"; then
        sed -i 's/^BOOT_ORDER=.*/BOOT_ORDER=0xf641/' "$TMP_CONFIG"
    else
        printf '\nBOOT_ORDER=0xf641\n' >> "$TMP_CONFIG"
    fi
    if grep -q '^POWER_OFF_ON_HALT=' "$TMP_CONFIG"; then
        sed -i 's/^POWER_OFF_ON_HALT=.*/POWER_OFF_ON_HALT=0/' "$TMP_CONFIG"
    else
        printf 'POWER_OFF_ON_HALT=0\n' >> "$TMP_CONFIG"
    fi
    rpi-eeprom-config --apply "$TMP_CONFIG"
    rm -f "$TMP_CONFIG"
    log "CM5 EEPROM configured for SD, USB, then NVMe boot (BOOT_ORDER=0xf641)."
else
    log "rpi-eeprom-config is unavailable. The NVMe clone is complete, but boot order was not changed."
fi

sync
log "NVMe provisioning complete."
echo
echo "The uConsole will shut down."
echo "After shutdown, remove the SD card and power it back on."
shutdown -h now
