# MINTS SCADA Software - Makefile


# Variables

SHELL := /bin/bash

PYTHON := python3
VENV := .venv
VENV_ACTIVATE := $(VENV)/bin/activate
REQUIREMENTS := requirements.txt

BACKEND := main_backend.py
GUI := main_user_gui.py
BACKEND_SOCKET := .backend_service.sock

DEV_DIR := .dev
BACKEND_PID_FILE := $(DEV_DIR)/backend.pid
APPLICATION_PID_FILE := .applicationpid

HISTORY_DIRS := .ignitionraw .ignitionrawbak ignitionhistory
LOCAL_DEV_FILES := .guiworkspace.json
LOCAL_DEV_DIRS := .guimetadata

# Preserve demo/example runs generated for playback/integrity testing.
# These match timestamped run_ids like:
#   2026-03-14_12-34-56_demo_integrity_green
#   2026-03-14_12-34-57_demo_integrity_yellow_missing_rawbak
#   2026-03-14_12-34-58_demo_integrity_red_mismatch
PRESERVE_HISTORY_RUN_PATTERNS := \
	*demo_integrity_green \
	*demo_integrity_yellow_missing_rawbak \
	*demo_integrity_red_mismatch

.DEFAULT_GOAL := help

.PHONY: help setup wsl-usb usb-status run run-direct run-backend run-gui stop restart status \
	clear-all-history clean clean-dev \
	_ensure-dev-dirs _ensure-venv _ensure-history-dirs


help:
	@echo "MINTS SCADA Software - Available Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make setup              - Create venv, install deps, and print USB setup notes"
	@echo "  make wsl-usb            - Configure USB device forwarding (WSL only)"
	@echo ""
	@echo "Run:"
	@echo "  make run                - Show USB/serial status, then start backend + GUI"
	@echo "  make run-direct         - Start backend + GUI immediately, skip USB check"
	@echo "  make run-backend        - Start backend only"
	@echo "  make run-gui            - Start GUI only (backend must already be running)"
	@echo "  make usb-status         - Show current USB and serial device status"
	@echo ""
	@echo "Control:"
	@echo "  make stop               - Stop processes started by this Makefile"
	@echo "  make restart            - Stop all app processes, then run full startup again"
	@echo "  make status             - Show backend, watcher, socket, and local history status"
	@echo ""
	@echo "Dev cleanup:"
	@echo "  These are for software dev only and will be removed. Please do not use."
	@echo "  make clear-all-history  - Clear history contents but preserve .gitkeep and preserved demo runs"
	@echo "  make clean-dev          - Remove dev pid/socket files"
	@echo "  make clean              - Full dev reset: history + .dev + GUI metadata (preserves demo runs)"
	@echo ""
	@echo "Notes:"
	@echo "  'make run' no longer prompts during startup."
	@echo "  On WSL, use 'make wsl-usb' separately if you need USB forwarding."
	@echo "  Demo integrity runs are preserved during cleanup."


# Create venv and install dependencies
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
		echo "Run 'make wsl-usb' if you need to forward a USB device from Windows to WSL."; \
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
wsl-usb:
	@./install-system-deps.sh


usb-status:
	@echo "=== Current USB/Serial Port Status ==="
	@echo ""
	@if grep -qEi "(Microsoft|WSL)" /proc/version 2>/dev/null; then \
		echo "USB Devices:"; \
		echo "  (WSL detected: skipping lsusb to avoid startup hangs)"; \
		echo "  Run 'make wsl-usb' if you need USB forwarding."; \
	else \
		if command -v lsusb > /dev/null 2>&1; then \
			echo "USB Devices:"; \
			lsusb 2>/dev/null || echo "  (lsusb failed)"; \
		else \
			echo "USB Devices:"; \
			echo "  (lsusb not available)"; \
		fi; \
	fi
	@echo ""
	@echo "Serial Ports:"
	@ports=$$(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true); \
	if [ -n "$$ports" ]; then \
		echo "$$ports"; \
	else \
		echo "  (none found)"; \
	fi
	@echo ""


run: usb-status run-direct


run-direct:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Error: Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@mkdir -p "$(DEV_DIR)"
	@mkdir -p .ignitionraw .ignitionrawbak ignitionhistory
	@touch .ignitionraw/.gitkeep .ignitionrawbak/.gitkeep ignitionhistory/.gitkeep
	@set -eu; \
	started_backend=0; \
	if [ -f "$(BACKEND_PID_FILE)" ]; then \
		pid=$$(cat "$(BACKEND_PID_FILE)" 2>/dev/null || true); \
		if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
			echo "[INFO] Backend already running with pid=$$pid"; \
		else \
			echo "[INFO] Removing stale backend pid file"; \
			rm -f "$(BACKEND_PID_FILE)"; \
		fi; \
	fi; \
	if [ -S "$(BACKEND_SOCKET)" ] && [ ! -f "$(BACKEND_PID_FILE)" ]; then \
		echo "[INFO] Removing stale backend socket $(BACKEND_SOCKET)"; \
		rm -f "$(BACKEND_SOCKET)"; \
	fi; \
	if [ ! -f "$(BACKEND_PID_FILE)" ]; then \
		echo "[INFO] Starting backend..."; \
		nohup bash -lc 'source "$(VENV_ACTIVATE)" && exec $(PYTHON) $(BACKEND)' >/dev/null 2>&1 & \
		backend_pid=$$!; \
		echo "$$backend_pid" > "$(BACKEND_PID_FILE)"; \
		started_backend=1; \
	else \
		backend_pid=$$(cat "$(BACKEND_PID_FILE)" 2>/dev/null || true); \
	fi; \
	echo "[INFO] Waiting for backend socket $(BACKEND_SOCKET)..."; \
	for i in $$(seq 1 80); do \
		if [ -S "$(BACKEND_SOCKET)" ]; then \
			echo "[OK] Backend socket is ready"; \
			break; \
		fi; \
		sleep 0.25; \
	done; \
	if [ ! -S "$(BACKEND_SOCKET)" ]; then \
		echo "[ERROR] Backend socket did not appear."; \
		if [ "$$started_backend" -eq 1 ]; then \
			pid=$$(cat "$(BACKEND_PID_FILE)" 2>/dev/null || true); \
			if [ -n "$$pid" ]; then kill "$$pid" 2>/dev/null || true; fi; \
			rm -f "$(BACKEND_PID_FILE)"; \
		fi; \
		exit 1; \
	fi; \
	cleanup() { \
		gui_code=$$?; \
		echo "[INFO] Shutting down application processes..."; \
		if [ -f "$(APPLICATION_PID_FILE)" ]; then \
			while IFS= read -r pid_line; do \
				pid=$$(echo "$$pid_line" | awk '{print $$1}'); \
				label=$$(echo "$$pid_line" | cut -d' ' -f2-); \
				if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
					echo "[INFO] Terminating $$label (pid=$$pid)"; \
					kill "$$pid" 2>/dev/null || true; \
				fi; \
			done < "$(APPLICATION_PID_FILE)"; \
			sleep 1.5; \
			while IFS= read -r pid_line; do \
				pid=$$(echo "$$pid_line" | awk '{print $$1}'); \
				label=$$(echo "$$pid_line" | cut -d' ' -f2-); \
				if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
					echo "[WARN] Force killing $$label (pid=$$pid)"; \
					kill -9 "$$pid" 2>/dev/null || true; \
				fi; \
			done < "$(APPLICATION_PID_FILE)"; \
			rm -f "$(APPLICATION_PID_FILE)"; \
		fi; \
		if [ "$$started_backend" -eq 1 ]; then \
			rm -f "$(BACKEND_PID_FILE)" "$(BACKEND_SOCKET)"; \
		fi; \
		rm -f .shutdown_signal; \
		echo "[OK] Application shutdown complete"; \
		exit "$$gui_code"; \
	}; \
	trap cleanup EXIT INT TERM; \
	rm -f "$(APPLICATION_PID_FILE)" .shutdown_signal; \
	if [ "$$started_backend" -eq 1 ]; then \
		echo "$$backend_pid backend" >> "$(APPLICATION_PID_FILE)"; \
	fi; \
	echo "[INFO] Starting shutdown watcher..."; \
	nohup bash -lc 'source "$(VENV_ACTIVATE)" && exec $(PYTHON) gui/shutdown_watcher.py' >/dev/null 2>&1 & \
	watcher_pid=$$!; \
	echo "$$watcher_pid shutdown_watcher" >> "$(APPLICATION_PID_FILE)"; \
	echo "[INFO] Starting GUI..."; \
	. "$(VENV_ACTIVATE)" && $(PYTHON) $(GUI)


run-backend:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Error: Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@mkdir -p "$(DEV_DIR)"
	@mkdir -p .ignitionraw .ignitionrawbak ignitionhistory
	@touch .ignitionraw/.gitkeep .ignitionrawbak/.gitkeep ignitionhistory/.gitkeep
	@set -eu; \
	if [ -f "$(BACKEND_PID_FILE)" ]; then \
		pid=$$(cat "$(BACKEND_PID_FILE)" 2>/dev/null || true); \
		if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
			echo "[INFO] Backend already running with pid=$$pid"; \
			exit 0; \
		else \
			echo "[INFO] Removing stale backend pid file"; \
			rm -f "$(BACKEND_PID_FILE)"; \
		fi; \
	fi; \
	if [ -S "$(BACKEND_SOCKET)" ]; then \
		echo "[INFO] Removing stale backend socket $(BACKEND_SOCKET)"; \
		rm -f "$(BACKEND_SOCKET)"; \
	fi; \
	echo "[INFO] Starting backend..."; \
	nohup bash -lc 'source "$(VENV_ACTIVATE)" && exec $(PYTHON) $(BACKEND)' >/dev/null 2>&1 & \
	echo $$! > "$(BACKEND_PID_FILE)"; \
	echo "[OK] Backend started with pid=$$(cat "$(BACKEND_PID_FILE)")"


run-gui:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Error: Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@mkdir -p .ignitionraw .ignitionrawbak ignitionhistory
	@touch .ignitionraw/.gitkeep .ignitionrawbak/.gitkeep ignitionhistory/.gitkeep
	@echo "[INFO] Starting GUI only..."
	@. "$(VENV_ACTIVATE)" && exec $(PYTHON) $(GUI)


stop:
	@set -eu; \
	stopped_any=0; \
	if [ -f "$(APPLICATION_PID_FILE)" ]; then \
		echo "[INFO] Stopping application processes from $(APPLICATION_PID_FILE)..."; \
		while IFS= read -r pid_line; do \
			pid=$$(echo "$$pid_line" | awk '{print $$1}'); \
			label=$$(echo "$$pid_line" | cut -d' ' -f2-); \
			if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
				echo "[INFO] Terminating $$label (pid=$$pid)"; \
				kill "$$pid" 2>/dev/null || true; \
				stopped_any=1; \
			fi; \
		done < "$(APPLICATION_PID_FILE)"; \
		sleep 1; \
		while IFS= read -r pid_line; do \
			pid=$$(echo "$$pid_line" | awk '{print $$1}'); \
			label=$$(echo "$$pid_line" | cut -d' ' -f2-); \
			if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
				echo "[WARN] Force killing $$label (pid=$$pid)"; \
				kill -9 "$$pid" 2>/dev/null || true; \
				stopped_any=1; \
			fi; \
		done < "$(APPLICATION_PID_FILE)"; \
		rm -f "$(APPLICATION_PID_FILE)"; \
	fi; \
	if [ -f "$(BACKEND_PID_FILE)" ]; then \
		pid=$$(cat "$(BACKEND_PID_FILE)" 2>/dev/null || true); \
		if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
			echo "[INFO] Stopping backend pid=$$pid"; \
			kill "$$pid" 2>/dev/null || true; \
			sleep 1; \
			kill -0 "$$pid" 2>/dev/null && kill -9 "$$pid" 2>/dev/null || true; \
			stopped_any=1; \
		else \
			echo "[INFO] Backend pid file exists but process is not alive"; \
		fi; \
	fi; \
	rm -f "$(BACKEND_PID_FILE)" "$(BACKEND_SOCKET)" .shutdown_signal; \
	if [ "$$stopped_any" -eq 1 ]; then \
		echo "[OK] Application stopped"; \
	else \
		echo "[INFO] No running application processes found"; \
	fi


restart: stop run


status:
	@echo "=== MINTS SCADA Status ==="
	@echo "Backend socket: $(BACKEND_SOCKET)"
	@if [ -S "$(BACKEND_SOCKET)" ]; then echo "  [OK] socket exists"; else echo "  [--] socket missing"; fi
	@if [ -f "$(BACKEND_PID_FILE)" ]; then \
		pid=$$(cat "$(BACKEND_PID_FILE)" 2>/dev/null || true); \
		if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
			echo "Backend PID: $$pid [alive]"; \
		else \
			echo "Backend PID file exists but process is dead"; \
		fi; \
	else \
		echo "Backend PID: [none]"; \
	fi
	@if [ -f "$(APPLICATION_PID_FILE)" ]; then \
		echo "Application PID file: $(APPLICATION_PID_FILE) [present]"; \
		while IFS= read -r pid_line; do \
			pid=$$(echo "$$pid_line" | awk '{print $$1}'); \
			label=$$(echo "$$pid_line" | cut -d' ' -f2-); \
			if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
				echo "  [OK] $$label pid=$$pid"; \
			else \
				echo "  [--] $$label pid=$$pid not alive"; \
			fi; \
		done < "$(APPLICATION_PID_FILE)"; \
	else \
		echo "Application PID file: [none]"; \
	fi
	@echo "History roots:"
	@for d in $(HISTORY_DIRS); do \
		if [ -d "$$d" ]; then \
			echo "  [OK] $$d"; \
		else \
			echo "  [--] $$d missing"; \
		fi; \
	done
	@echo "Preserved history patterns:"
	@for p in $(PRESERVE_HISTORY_RUN_PATTERNS); do \
		echo "  [KEEP] $$p"; \
	done
	@echo "Local dev files:"
	@for f in $(LOCAL_DEV_FILES); do \
		if [ -f "$$f" ]; then echo "  [OK] $$f"; else echo "  [--] $$f missing"; fi; \
	done
	@echo "Local dev dirs:"
	@for d in $(LOCAL_DEV_DIRS); do \
		if [ -d "$$d" ]; then echo "  [OK] $$d"; else echo "  [--] $$d missing"; fi; \
	done


clear-all-history:
	@mkdir -p .ignitionraw .ignitionrawbak ignitionhistory
	@touch .ignitionraw/.gitkeep .ignitionrawbak/.gitkeep ignitionhistory/.gitkeep
	@echo "[WARN] Clearing dev history contents but preserving .gitkeep and preserved demo runs..."
	@set -eu; \
	should_preserve() { \
		local name="$$1"; \
		if [ "$$name" = ".gitkeep" ]; then \
			return 0; \
		fi; \
		for pattern in $(PRESERVE_HISTORY_RUN_PATTERNS); do \
			case "$$name" in $$pattern) return 0 ;; esac; \
		done; \
		return 1; \
	}; \
	for d in $(HISTORY_DIRS); do \
		for entry in "$$d"/* "$$d"/.*; do \
			[ ! -e "$$entry" ] && continue; \
			name=$$(basename "$$entry"); \
			[ "$$name" = "." ] || [ "$$name" = ".." ] && continue; \
			if should_preserve "$$name"; then \
				echo "  [KEEP] $$entry"; \
				continue; \
			fi; \
			echo "  [RM] $$entry"; \
			rm -rf "$$entry"; \
		done; \
		touch "$$d/.gitkeep"; \
	done
	@echo "[OK] Cleared history contents and preserved .gitkeep + demo runs"


clean: stop clear-all-history
	@echo "[WARN] Removing local dev-only metadata and scratch directories..."
	@rm -f $(LOCAL_DEV_FILES)
	@rm -rf $(LOCAL_DEV_DIRS)
	@rm -rf "$(DEV_DIR)"
	@echo "[OK] Full dev cleanup complete"


clean-dev:
	@echo "[INFO] Cleaning dev artifacts..."
	@rm -f "$(BACKEND_PID_FILE)" "$(BACKEND_SOCKET)" "$(APPLICATION_PID_FILE)" .shutdown_signal
	@rmdir "$(DEV_DIR)" 2>/dev/null || true
	@echo "[OK] Dev artifacts cleaned"


_ensure-dev-dirs:
	@mkdir -p "$(DEV_DIR)"


_ensure-venv:
	@if [ ! -d "$(VENV)" ]; then \
		echo "[ERROR] Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi


_ensure-history-dirs:
	@mkdir -p .ignitionraw .ignitionrawbak ignitionhistory
	@touch .ignitionraw/.gitkeep .ignitionrawbak/.gitkeep ignitionhistory/.gitkeep