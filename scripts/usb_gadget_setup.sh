#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# usb_gadget_setup.sh
# Configures Raspberry Pi Zero as USB HID keyboard or mass storage.
#
# Usage:
#   sudo ./usb_gadget_setup.sh keyboard      — HID keyboard mode
#   sudo ./usb_gadget_setup.sh storage       — USB mass storage mode
#   sudo ./usb_gadget_setup.sh eject         — safely eject + sync files
#   sudo ./usb_gadget_setup.sh off           — disable gadget

GADGET_DIR="/sys/kernel/config/usb_gadget/pigadget"
MODE="${1:-keyboard}"
IMG="$PROJECT_DIR/usb_storage.img"
FILES_DIR="$PROJECT_DIR/menu_fs/04_files"
MNT="/tmp/pigadget_mnt"

_unmount() {
    if mountpoint -q "$MNT" 2>/dev/null; then
        umount "$MNT" 2>/dev/null || umount -l "$MNT" 2>/dev/null || true
    fi
}

_teardown() {
    [ ! -d "$GADGET_DIR" ] && return 0
    echo "" > "$GADGET_DIR/UDC" 2>/dev/null || true
    sleep 1
    for f in "$GADGET_DIR"/configs/c.1/hid.usb0 \
              "$GADGET_DIR"/configs/c.1/mass_storage.0; do
        [ -L "$f" ] && rm -f "$f" 2>/dev/null || true
    done
    rmdir "$GADGET_DIR/functions/hid.usb0"             2>/dev/null || true
    rmdir "$GADGET_DIR/functions/mass_storage.0/lun.0" 2>/dev/null || true
    rmdir "$GADGET_DIR/functions/mass_storage.0"       2>/dev/null || true
    rmdir "$GADGET_DIR/configs/c.1/strings/0x409"      2>/dev/null || true
    rmdir "$GADGET_DIR/configs/c.1"                    2>/dev/null || true
    rmdir "$GADGET_DIR/strings/0x409"                  2>/dev/null || true
    rmdir "$GADGET_DIR"                                2>/dev/null || true
    sleep 0.3
}

_sync_to_img() {
    echo "[USB Gadget] Syncing files -> image..."
    mkdir -p "$MNT" "$FILES_DIR/payloads"
    _unmount
    if [ ! -f "$IMG" ]; then
        echo "[USB Gadget] Creating 256MB storage image..."
        dd if=/dev/zero of="$IMG" bs=1M count=256 status=none
        mkfs.fat -F 32 -n "PIGADGET" "$IMG"
    fi
    mount -o loop,uid=1000,gid=1000 "$IMG" "$MNT"
    cp -r "$FILES_DIR/." "$MNT/" 2>/dev/null || true
    sync
    _unmount
    echo "[USB Gadget] Sync to image done."
}

_sync_from_img() {
    echo "[USB Gadget] Syncing image -> files..."
    mkdir -p "$MNT" "$FILES_DIR"
    _unmount
    [ ! -f "$IMG" ] && echo "[USB Gadget] No image, skipping." && return 0
    mount -o loop,uid=1000,gid=1000 "$IMG" "$MNT"
    # Copy everything except Windows junk
    find "$MNT" -mindepth 1 -maxdepth 1 \
        ! -name 'System Volume Information' \
        ! -name '$RECYCLE.BIN' \
        ! -name '.Trashes' \
        ! -name '.Spotlight-V100' \
        -exec cp -r {} "$FILES_DIR/" \; 2>/dev/null || true
    sync
    _unmount
    # Auto-import payloads
    PAYLOAD_DST="$PROJECT_DIR/apps/tools/payload/payloads"
    mkdir -p "$PAYLOAD_DST"
    find "$FILES_DIR/payloads" -name "*.ds" -o -name "*.payload" 2>/dev/null | \
    while read f; do
        cp "$f" "$PAYLOAD_DST/"
        echo "[USB Gadget] Payload imported: $(basename $f)"
    done
    echo "[USB Gadget] Sync from image done."
}

# ── Commands ──────────────────────────────────────────────────
if [ "$MODE" = "eject" ]; then
    _teardown
    _sync_from_img
    echo "[USB Gadget] Ejected and synced."
    exit 0
fi

if [ "$MODE" = "off" ]; then
    _teardown
    echo "[USB Gadget] Disabled."
    exit 0
fi

_teardown

mkdir -p "$GADGET_DIR"
echo 0x1d6b > "$GADGET_DIR/idVendor"
echo 0x0104 > "$GADGET_DIR/idProduct"
echo 0x0100 > "$GADGET_DIR/bcdDevice"
echo 0x0200 > "$GADGET_DIR/bcdUSB"
mkdir -p "$GADGET_DIR/strings/0x409"
echo "deadbeef01" > "$GADGET_DIR/strings/0x409/serialnumber"
echo "Pi Gadget"  > "$GADGET_DIR/strings/0x409/manufacturer"
echo "Pi Gadget"  > "$GADGET_DIR/strings/0x409/product"
mkdir -p "$GADGET_DIR/configs/c.1"
echo 250 > "$GADGET_DIR/configs/c.1/MaxPower"
mkdir -p "$GADGET_DIR/configs/c.1/strings/0x409"

if [ "$MODE" = "keyboard" ]; then
    echo "HID Keyboard" > "$GADGET_DIR/configs/c.1/strings/0x409/configuration"
    mkdir -p "$GADGET_DIR/functions/hid.usb0"
    echo 1 > "$GADGET_DIR/functions/hid.usb0/protocol"
    echo 1 > "$GADGET_DIR/functions/hid.usb0/subclass"
    echo 8 > "$GADGET_DIR/functions/hid.usb0/report_length"
    echo -ne '\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x03\x95\x05\x75\x01\x05\x08\x19\x01\x29\x05\x91\x02\x95\x01\x75\x03\x91\x03\x95\x06\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0' \
        > "$GADGET_DIR/functions/hid.usb0/report_desc"
    ln -s "$GADGET_DIR/functions/hid.usb0" "$GADGET_DIR/configs/c.1/"
    echo "[USB Gadget] HID Keyboard mode active."

elif [ "$MODE" = "storage" ]; then
    echo "Mass Storage" > "$GADGET_DIR/configs/c.1/strings/0x409/configuration"
    _sync_to_img
    mkdir -p "$GADGET_DIR/functions/mass_storage.0"
    echo 1     > "$GADGET_DIR/functions/mass_storage.0/stall"
    mkdir -p "$GADGET_DIR/functions/mass_storage.0/lun.0"
    echo "$IMG" > "$GADGET_DIR/functions/mass_storage.0/lun.0/file"
    echo 0     > "$GADGET_DIR/functions/mass_storage.0/lun.0/cdrom"
    echo 0     > "$GADGET_DIR/functions/mass_storage.0/lun.0/ro"
    echo 0     > "$GADGET_DIR/functions/mass_storage.0/lun.0/nofua"
    ln -s "$GADGET_DIR/functions/mass_storage.0" "$GADGET_DIR/configs/c.1/"
    echo "[USB Gadget] Mass Storage mode active."
fi

UDC=$(ls /sys/class/udc 2>/dev/null | head -1)
if [ -z "$UDC" ]; then
    echo "[USB Gadget] ERROR: No UDC found."
    exit 1
fi
echo "$UDC" > "$GADGET_DIR/UDC"
echo "[USB Gadget] Bound to UDC: $UDC"

if [ "$MODE" = "keyboard" ]; then
    sleep 0.3
    if [ -e /dev/hidg0 ]; then
        chown root:input /dev/hidg0
        chmod 660 /dev/hidg0
        echo "[USB Gadget] /dev/hidg0 permissions set."
    fi
fi
