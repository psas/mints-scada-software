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

.PHONY: help setup wsl-usb run run-direct run-backend run-gui stop restart status \
	clear-all-history clean clean-dev \
	_ensure-dev-dirs _ensure-venv _ensure-history-dirs \
	_show-usb-status _maybe-wsl-usb _preflight-usb


help:
	@echo "MINTS SCADA Software - Available Commands"
	@echo ""
	@echo "Setup:"
	@echo " make setup - Create virtual environment, install dependencies, then run USB/serial preflight"
	@echo " make wsl-usb - Configure USB device forwarding (WSL only)"
	@echo ""
	@echo "Run:"
	@echo " make run - Run USB/serial preflight, start backend, wait for socket, then start GUI"
	@echo " make run-backend - Run USB/serial preflight, then start backend only"
	@echo " make run-gui - Run USB/serial preflight, then start GUI only"
	@echo " make run-direct - Start GUI only without USB/serial preflight"
	@echo ""
	@echo "Control:"
	@echo " make stop - Stop backend started by this Makefile"
	@echo " make restart - Stop backend, then run full startup again"
	@echo " make status - Show backend, socket, and local history status"
	@echo ""
	@echo "Dev cleanup:"
	@echo " These are for software dev only and will be removed. Please do not use."
	@echo " make clear-all-history - Clear history contents but preserve .gitkeep and preserved demo runs"
	@echo " make clean-dev - Remove dev pid/socket files"
	@echo " make clean - Full dev reset: history + .dev + GUI metadata (preserves demo runs)"
	@echo ""
	@echo "Notes:"
	@echo " Startup targets run USB/serial preflight before launching anything."
	@echo " Use 'make run-direct' only when you intentionally want to skip that check."
	@echo " Demo integrity runs are preserved during cleanup."


setup:
	@$(MAKE) _preflight-usb
	@$(MAKE) _ensure-dev-dirs
	@$(MAKE) _ensure-history-dirs
	@echo "Creating virtual environment..."
	$(PYTHON) -m venv $(VENV)
	@echo "Installing dependencies..."
	@source "$(VENV_ACTIVATE)" && pip install -r $(REQUIREMENTS)
	@echo ""
	@echo "[OK] Setup complete"
	@echo "To run: make run"


# WSL USB port forwarding setup (optional, WSL users only)
wsl-usb:
	@./install-system-deps.sh


run:
	@$(MAKE) _preflight-usb
	@$(MAKE) _ensure-dev-dirs
	@$(MAKE) _ensure-venv
	@$(MAKE) _ensure-history-dirs
	@set -euo pipefail; \
	started_backend=0; \
	if [[ -f "$(BACKEND_PID_FILE)" ]]; then \
		pid=$$(cat "$(BACKEND_PID_FILE)" 2>/dev/null || true); \
		if [[ -n "$$pid" ]] && kill -0 "$$pid" 2>/dev/null; then \
			echo "[INFO] Backend already running with pid=$$pid"; \
		else \
			echo "[INFO] Removing stale backend pid file"; \
			rm -f "$(BACKEND_PID_FILE)"; \
		fi; \
	fi; \
	if [[ -S "$(BACKEND_SOCKET)" && ! -f "$(BACKEND_PID_FILE)" ]]; then \
		echo "[INFO] Removing stale backend socket $(BACKEND_SOCKET)"; \
		rm -f "$(BACKEND_SOCKET)"; \
	fi; \
	if [[ ! -f "$(BACKEND_PID_FILE)" ]]; then \
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
		if [[ -S "$(BACKEND_SOCKET)" ]]; then \
			echo "[OK] Backend socket is ready"; \
			break; \
		fi; \
		sleep 0.25; \
	done; \
	if [[ ! -S "$(BACKEND_SOCKET)" ]]; then \
		echo "[ERROR] Backend socket did not appear."; \
		if [[ "$$started_backend" -eq 1 ]]; then \
			pid=$$(cat "$(BACKEND_PID_FILE)" 2>/dev/null || true); \
			if [[ -n "$$pid" ]]; then kill "$$pid" 2>/dev/null || true; fi; \
			rm -f "$(BACKEND_PID_FILE)"; \
		fi; \
		exit 1; \
	fi; \
	cleanup() { \
		gui_code=$$?; \
		echo "[INFO] Shutting down all application processes..."; \
		if [[ -f "$(APPLICATION_PID_FILE)" ]]; then \
			while IFS= read -r pid_line; do \
				pid=$$(echo "$$pid_line" | awk '{print $$1}'); \
				label=$$(echo "$$pid_line" | cut -d' ' -f2-); \
				if [[ -n "$$pid" ]] && kill -0 "$$pid" 2>/dev/null; then \
					echo "[INFO] Terminating $$label (pid=$$pid)"; \
					kill "$$pid" 2>/dev/null || true; \
				fi; \
			done < "$(APPLICATION_PID_FILE)"; \
			sleep 1.5; \
			while IFS= read -r pid_line; do \
				pid=$$(echo "$$pid_line" | awk '{print $$1}'); \
				label=$$(echo "$$pid_line" | cut -d' ' -f2-); \
				if [[ -n "$$pid" ]] && kill -0 "$$pid" 2>/dev/null; then \
					echo "[WARN] Force killing $$label (pid=$$pid)"; \
					kill -9 "$$pid" 2>/dev/null || true; \
				fi; \
			done < "$(APPLICATION_PID_FILE)"; \
			rm -f "$(APPLICATION_PID_FILE)"; \
		fi; \
		rm -f "$(BACKEND_PID_FILE)" "$(BACKEND_SOCKET)"; \
		echo "[OK] Application shutdown complete"; \
		exit "$$gui_code"; \
	}; \
	trap cleanup EXIT INT TERM; \
	rm -f "$(APPLICATION_PID_FILE)" .shutdown_signal; \
	echo "$$backend_pid backend" >> "$(APPLICATION_PID_FILE)"; \
	echo "[INFO] Starting shutdown watcher..."; \
	nohup bash -lc 'source "$(VENV_ACTIVATE)" && exec $(PYTHON) gui/shutdown_watcher.py' >/dev/null 2>&1 & \
	watcher_pid=$$!; \
	echo "$$watcher_pid shutdown_watcher" >> "$(APPLICATION_PID_FILE)"; \
	echo "[INFO] Starting GUI..."; \
	source "$(VENV_ACTIVATE)" && $(PYTHON) $(GUI)


run-backend:
	@$(MAKE) _preflight-usb
	@$(MAKE) _ensure-dev-dirs
	@$(MAKE) _ensure-venv
	@$(MAKE) _ensure-history-dirs
	@set -euo pipefail; \
	if [[ -f "$(BACKEND_PID_FILE)" ]]; then \
		pid=$$(cat "$(BACKEND_PID_FILE)" 2>/dev/null || true); \
		if [[ -n "$$pid" ]] && kill -0 "$$pid" 2>/dev/null; then \
			echo "[INFO] Backend already running with pid=$$pid"; \
			exit 0; \
		else \
			rm -f "$(BACKEND_PID_FILE)"; \
		fi; \
	fi; \
	[[ -S "$(BACKEND_SOCKET)" ]] && rm -f "$(BACKEND_SOCKET)"; \
	echo "[INFO] Starting backend..."; \
	nohup bash -lc 'source "$(VENV_ACTIVATE)" && exec $(PYTHON) $(BACKEND)' >/dev/null 2>&1 & \
	echo $$! > "$(BACKEND_PID_FILE)"; \
	echo "[OK] Backend started with pid=$$(cat "$(BACKEND_PID_FILE)")"


run-gui:
	@$(MAKE) _preflight-usb
	@$(MAKE) _ensure-venv
	@$(MAKE) _ensure-history-dirs
	@echo "[INFO] Starting GUI only..."
	@source "$(VENV_ACTIVATE)" && exec $(PYTHON) $(GUI)


# Start GUI directly without USB/serial preflight
run-direct:
	@$(MAKE) _ensure-venv
	@$(MAKE) _ensure-history-dirs
	@echo "[INFO] Starting GUI directly (USB/serial preflight skipped)..."
	@source "$(VENV_ACTIVATE)" && exec $(PYTHON) $(GUI)


stop:
	@set -euo pipefail; \
	if [[ ! -f "$(BACKEND_PID_FILE)" ]]; then \
		echo "[INFO] No backend pid file found"; \
		rm -f "$(BACKEND_SOCKET)"; \
		exit 0; \
	fi; \
	pid=$$(cat "$(BACKEND_PID_FILE)" 2>/dev/null || true); \
	if [[ -n "$$pid" ]] && kill -0 "$$pid" 2>/dev/null; then \
		echo "[INFO] Stopping backend pid=$$pid"; \
		kill "$$pid" 2>/dev/null || true; \
		sleep 1; \
		kill -0 "$$pid" 2>/dev/null && kill -9 "$$pid" 2>/dev/null || true; \
	else \
		echo "[INFO] Backend pid file exists but process is not alive"; \
	fi; \
	rm -f "$(BACKEND_PID_FILE)" "$(BACKEND_SOCKET)"; \
	echo "[OK] Backend stopped"


restart: stop run


status:
	@echo "=== MINTS SCADA Status ==="
	@echo "Backend socket: $(BACKEND_SOCKET)"
	@if [[ -S "$(BACKEND_SOCKET)" ]]; then echo " [OK] socket exists"; else echo " [--] socket missing"; fi
	@if [[ -f "$(BACKEND_PID_FILE)" ]]; then \
		pid=$$(cat "$(BACKEND_PID_FILE)" 2>/dev/null || true); \
		if [[ -n "$$pid" ]] && kill -0 "$$pid" 2>/dev/null; then \
			echo "Backend PID: $$pid [alive]"; \
		else \
			echo "Backend PID file exists but process is dead"; \
		fi; \
	else \
		echo "Backend PID: [none]"; \
	fi
	@echo "History roots:"
	@for d in $(HISTORY_DIRS); do \
		if [[ -d "$$d" ]]; then \
			echo " [OK] $$d"; \
		else \
			echo " [--] $$d missing"; \
		fi; \
	done
	@echo "Preserved history patterns:"
	@for p in $(PRESERVE_HISTORY_RUN_PATTERNS); do \
		echo " [KEEP] $$p"; \
	done
	@echo "Local dev files:"
	@for f in $(LOCAL_DEV_FILES); do \
		if [[ -f "$$f" ]]; then echo " [OK] $$f"; else echo " [--] $$f missing"; fi; \
	done
	@echo "Local dev dirs:"
	@for d in $(LOCAL_DEV_DIRS); do \
		if [[ -d "$$d" ]]; then echo " [OK] $$d"; else echo " [--] $$d missing"; fi; \
	done


clear-all-history: _ensure-history-dirs
	@echo "[WARN] Clearing dev history contents but preserving .gitkeep and preserved demo runs..."
	@set -euo pipefail; \
	should_preserve() { \
		local name="$$1"; \
		if [[ "$$name" == ".gitkeep" ]]; then \
			return 0; \
		fi; \
		for pattern in $(PRESERVE_HISTORY_RUN_PATTERNS); do \
			if [[ "$$name" == $$pattern ]]; then \
				return 0; \
			fi; \
		done; \
		return 1; \
	}; \
	for d in $(HISTORY_DIRS); do \
		for entry in "$$d"/* "$$d"/.*; do \
			[[ ! -e "$$entry" ]] && continue; \
			name=$$(basename "$$entry"); \
			[[ "$$name" == "." || "$$name" == ".." ]] && continue; \
			if should_preserve "$$name"; then \
				echo " [KEEP] $$entry"; \
				continue; \
			fi; \
			echo " [RM] $$entry"; \
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


_show-usb-status:
	@echo "=== Current USB/Serial Port Status ==="
	@echo ""
	@if command -v lsusb > /dev/null 2>&1; then \
		echo "USB Devices:"; \
		lsusb 2>/dev/null || echo " (none found)"; \
	else \
		echo "USB Devices:"; \
		echo " (lsusb not available)"; \
	fi
	@echo ""
	@echo "Serial Ports:"
	@if ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null; then \
		echo ""; \
	else \
		echo " (none found)"; \
	fi
	@echo ""


_maybe-wsl-usb:
	@if grep -qEi "(Microsoft|WSL)" /proc/version 2>/dev/null; then \
		echo "Detected WSL environment."; \
		read -p "Need to configure USB forwarding from Windows? (y/n): " answer; \
		if [[ "$$answer" == "y" || "$$answer" == "Y" ]]; then \
			$(MAKE) wsl-usb; \
			echo ""; \
			echo "[OK] USB forwarding step finished."; \
			echo ""; \
		else \
			echo "Skipping USB forwarding."; \
			echo ""; \
		fi; \
	else \
		echo "Running on native Linux - USB devices should be available directly."; \
		echo ""; \
	fi


_preflight-usb:
	@$(MAKE) _show-usb-status
	@$(MAKE) _maybe-wsl-usb


_ensure-dev-dirs:
	@mkdir -p "$(DEV_DIR)"


_ensure-venv:
	@if [[ ! -d "$(VENV)" ]]; then \
		echo "[ERROR] Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi


_ensure-history-dirs:
	@mkdir -p .ignitionraw .ignitionrawbak ignitionhistory
	@touch .ignitionraw/.gitkeep .ignitionrawbak/.gitkeep ignitionhistory/.gitkeep