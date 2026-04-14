#!/bin/bash
# bootstrap/wsl-usb.sh -- WSL USB COM port forwarding setup.
#
# Interactive script to install USB tools and forward a USB device
# from Windows into WSL. WSL-only; exits cleanly on native Linux.
# This is the implementation behind `make wsl-usb`.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

#  WSL USB dependency list 
#
# Packages needed inside WSL for USB forwarding.
WSL_USB_DEPS=(
    usbutils            # lsusb
    linux-tools-generic # usbip client
    hwdata              # USB device database
)

#  Dependency check and install 

install_wsl_usb_deps() {
    local missing=()
    for pkg in "${WSL_USB_DEPS[@]}"; do
        if ! dpkg -s "$pkg" &>/dev/null; then
            missing+=("$pkg")
        fi
    done

    if [[ ${#missing[@]} -eq 0 ]]; then
        ok "USB tools already installed."
        return 0
    fi

    echo "This system is missing USB/serial packages:"
    for pkg in "${missing[@]}"; do
        echo "  - $pkg"
    done
    echo ""
    echo "The following packages will be installed on this computer:"
    for pkg in "${missing[@]}"; do
        echo "  - $pkg"
    done

    if ! confirm "Install these packages? (requires sudo)"; then
        info "Installation cancelled."
        info "You can install them manually: sudo apt-get install -y ${missing[*]}"
        exit 0
    fi

    echo ""
    info "Updating package lists..."
    sudo apt-get update -qq
    info "Installing USB tools..."
    sudo apt-get install -y "${missing[@]}"
    echo ""
    ok "USB tools installed."
}

#  Main 

main() {
    echo "=== WSL USB COM Port Forwarding Setup ==="
    echo ""

    if ! is_wsl; then
        echo "This script is for WSL (Windows Subsystem for Linux) only."
        echo "You appear to be running native Linux."
        echo ""
        echo "On native Linux, USB devices are already available at /dev/ttyUSB* or /dev/ttyACM*"
        echo "No forwarding is needed."
        echo ""
        exit 0
    fi

    # Install USB tools if needed.
    install_wsl_usb_deps
    echo ""

    # Check if usbipd is installed on Windows.
    info "Checking for usbipd-win on Windows..."
    if ! powershell.exe -Command "Get-Command usbipd" >/dev/null 2>&1; then
        echo ""
        warn "usbipd-win is not installed on Windows!"
        echo ""
        echo "Please install it first by running this in Windows PowerShell (as Administrator):"
        echo "  winget install --interactive --exact dorssel.usbipd-win"
        echo ""
        echo "After installation, restart your terminal and run 'make wsl-usb' again."
        exit 1
    fi

    ok "usbipd-win found!"
    echo ""

    # List available USB devices.
    echo "=== Available USB Devices on Windows ==="
    echo ""
    powershell.exe -Command "usbipd list" 2>/dev/null | tr -d '\r'
    echo ""

    echo "[TIP] Look for devices with these keywords:"
    echo "      Serial | COM"
    echo ""

    # Prompt for BUSID.
    read -r -p "Enter the BUSID of your device (e.g., 1-4): " BUSID

    if [[ -z "$BUSID" ]]; then
        die "No BUSID provided. Exiting."
    fi

    echo ""
    echo "=== Forwarding device $BUSID to WSL ==="
    echo ""

    # Bind and attach the device (requires admin on first run).
    info "Binding device (may require Windows admin password)..."
    if powershell.exe -Command "Start-Process powershell -ArgumentList '-WindowStyle Hidden -Command \"usbipd bind --busid $BUSID 2>&1 | Out-Null; usbipd attach --wsl --busid $BUSID\"' -Verb RunAs -Wait -WindowStyle Hidden" 2>/dev/null; then
        ok "Device attached successfully!"
    else
        die "Failed to attach device. Make sure you approved the admin prompt."
    fi

    echo ""
    echo "=== Verifying Connection ==="
    echo ""

    # Wait for device to appear.
    sleep 2

    echo "USB devices in WSL:"
    lsusb 2>/dev/null || echo "  (lsusb not available)"
    echo ""

    echo "Available serial ports:"
    if ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null; then
        echo ""
        ok "Serial port is ready!"
    else
        echo "  (none found -- device might not be a serial port)"
    fi

    echo ""
    echo "=== Setup Complete! ==="
    echo ""
    ok "Device $BUSID is now forwarded to WSL."
    echo ""
    echo "Note: If you unplug and replug the device, run 'make wsl-usb' again."
    echo "Start your application with: make run"
    echo ""
}

main "$@"
