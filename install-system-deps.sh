#!/bin/bash
# WSL USB COM Port Forwarding Setup
# Interactive script to forward USB devices from Windows to WSL

# Check if running in WSL
if ! grep -qEi "(Microsoft|WSL)" /proc/version 2>/dev/null; then
    echo "=== System Check ==="
    echo ""
    echo "This script is for WSL (Windows Subsystem for Linux) only."
    echo "You appear to be running native Linux."
    echo ""
    echo "On native Linux, USB devices are already available at /dev/ttyUSB* or /dev/ttyACM*"
    echo "No forwarding is needed. You can run your application directly with: make run-direct"
    echo ""
    exit 0
fi

echo "=== WSL USB COM Port Forwarding Setup ==="
echo ""

# Install USB/serial port tools
echo "Installing USB and serial port tools..."
sudo apt-get update -qq
sudo apt-get install -y usbutils linux-tools-generic hwdata > /dev/null 2>&1

echo "[OK] USB tools installed!"
echo ""

# Check if usbipd is installed on Windows
echo "Checking for usbipd-win on Windows..."
if ! powershell.exe -Command "Get-Command usbipd" > /dev/null 2>&1; then
    echo ""
    echo "[!] WARNING: usbipd-win is not installed on Windows!"
    echo ""
    echo "Please install it first by running this in Windows PowerShell (as Administrator):"
    echo "  winget install --interactive --exact dorssel.usbipd-win"
    echo ""
    echo "After installation, restart your terminal and run 'make wsl-usb' again."
    exit 1
fi

echo "[OK] usbipd-win found!"
echo ""

# List available USB devices
echo "=== Available USB Devices on Windows ==="
echo ""
powershell.exe -Command "usbipd list" 2>/dev/null | tr -d '\r'
echo ""

# Highlight common serial device keywords
echo "[TIP] Look for devices with these keywords:"
echo "      Serial | COM"
echo ""

# Prompt for BUSID
read -p "Enter the BUSID of your device (e.g., 1-4): " BUSID

# Validate input
if [ -z "$BUSID" ]; then
    echo "[ERROR] No BUSID provided. Exiting."
    exit 1
fi

echo ""
echo "=== Forwarding device $BUSID to WSL ==="
echo ""

# Bind the device (requires admin on first run)
echo "Binding device (may require Windows admin password)..."
if ! powershell.exe -Command "Start-Process powershell -ArgumentList '-Command usbipd bind --busid $BUSID' -Verb RunAs -Wait" 2>/dev/null; then
    echo "[!] Bind failed. The device might already be bound."
fi

# Attach to WSL
echo "Attaching device to WSL..."
if powershell.exe -Command "Start-Process powershell -ArgumentList '-Command usbipd attach --wsl --busid $BUSID' -Verb RunAs -Wait" 2>/dev/null; then
    echo "[OK] Device attached successfully!"
else
    echo "[ERROR] Failed to attach device. Make sure you approved the admin prompt."
    exit 1
fi

echo ""
echo "=== Verifying Connection ==="
echo ""

# Wait a moment for device to appear
sleep 2

# Show USB devices in WSL
echo "USB devices in WSL:"
lsusb 2>/dev/null || echo "  (lsusb not available)"
echo ""

# Show serial ports
echo "Available serial ports:"
if ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null; then
    echo ""
    echo "[OK] Serial port is ready!"
else
    echo "  (none found - device might not be a serial port)"
fi

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "[OK] Device $BUSID is now forwarded to WSL."
echo ""
echo "Note: If you unplug and replug the device, run 'make wsl-usb' again."
echo "      Or simply use 'make run' which checks USB status automatically."
echo ""
echo "Start your application with: make run"
