# MINTS SCADA Software - Makefile

# Variables
PYTHON := python
VENV := .venv
VENV_ACTIVATE := $(VENV)/bin/activate
REQUIREMENTS := requirements.txt
MAIN := main.py

# Default target: show help
.PHONY: help
help:
	@echo "MINTS SCADA Software - Available Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make setup              - Create venv, install deps, optional USB setup"
	@echo "  make wsl-usb            - Configure USB device forwarding (WSL only)"
	@echo ""
	@echo "Run:"
	@echo "  make run                - Check USB status, then start application"
	@echo "  make run-direct         - Start application without USB check"
	@echo ""
	@echo "Notes:"
	@echo "  'make run' shows current USB/serial connections and prompts"
	@echo "  if you need to configure USB forwarding before starting."
	@echo "  Use 'make run-direct' to skip the check and run immediately."
	@echo ""

# Create venv and install dependencies (matches README instructions)
.PHONY: setup
setup:
	@echo "Creating virtual environment..."
	$(PYTHON) -m venv $(VENV)
	@echo "Installing dependencies..."
	@. $(VENV_ACTIVATE) && pip install -r $(REQUIREMENTS)
	@echo ""
	@echo "[OK] Python setup complete!"
	@echo ""
	@if grep -qEi "(Microsoft|WSL)" /proc/version 2>/dev/null; then \
		echo "=== WSL USB Setup (Optional) ==="; \
		echo ""; \
		echo "Detected WSL environment."; \
		read -p "Do you need to forward a USB device from Windows to WSL? (y/n): " answer; \
		if [ "$$answer" = "y" ] || [ "$$answer" = "Y" ]; then \
			$(MAKE) wsl-usb; \
		else \
			echo "Skipping USB setup. Run 'make wsl-usb' later if needed."; \
		fi; \
	else \
		echo "Detected native Linux - USB devices should be available directly."; \
		echo "No USB forwarding needed."; \
		echo "Make sure you connected the COM switch to your computer."; \
	fi
	@echo ""
	@echo "[OK] Setup complete!"
	@echo "To run: make run"
	@echo ""

# WSL USB port forwarding setup (optional, WSL users only)
.PHONY: wsl-usb
wsl-usb:
	@./install-system-deps.sh

# Start the application (matches README run instructions)
.PHONY: run
run:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Error: Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@echo "Starting MINTS SCADA application..."
	@echo ""
	@echo "=== Current USB/Serial Port Status ==="
	@echo ""
	@if command -v lsusb > /dev/null 2>&1; then \
		echo "USB Devices:"; \
		lsusb 2>/dev/null || echo "  (none found)"; \
	else \
		echo "USB Devices:"; \
		echo "  (lsusb not available)"; \
	fi
	@echo ""
	@echo "Serial Ports:"
	@if ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null; then \
		echo ""; \
	else \
		echo "  (none found)"; \
	fi
	@echo ""
	@if grep -qEi "(Microsoft|WSL)" /proc/version 2>/dev/null; then \
		read -p "Need to configure USB forwarding from Windows? (y/n): " answer; \
		if [ "$$answer" = "y" ] || [ "$$answer" = "Y" ]; then \
			$(MAKE) wsl-usb; \
			echo ""; \
			echo "USB setup complete. Starting application..."; \
			echo ""; \
		fi; \
	else \
		echo "Running on native Linux - USB devices should be available directly."; \
		echo ""; \
	fi
	@. $(VENV_ACTIVATE) && python $(MAIN)

# Start the application directly (no USB check)
.PHONY: run-direct
run-direct:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Error: Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@echo "Starting MINTS SCADA application..."
	@. $(VENV_ACTIVATE) && python $(MAIN)
