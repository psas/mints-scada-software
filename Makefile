# MINTS SCADA Software - Makefile


# Variables

SHELL := /bin/bash

PYTHON := python3
VENV := .venv
VENV_ACTIVATE := $(VENV)/bin/activate
REQUIREMENTS := requirements.txt

GATEWAY := -m gateway.main
BACKEND := -m backend.main
GUI := -m gui.main
GATEWAY_SOCKET := .gateway_service.sock
BACKEND_SOCKET := .backend_service.sock

DEV_DIR := .dev
GATEWAY_PID_FILE := $(DEV_DIR)/gateway.pid
BACKEND_PID_FILE := $(DEV_DIR)/backend.pid
APPLICATION_PID_FILE := .applicationpid

HISTORY_DIRS := .ignitionraw .ignitionrawbak ignitionhistory
LOCAL_DEV_FILES := .guiworkspace.json
LOCAL_DEV_DIRS := .guimetadata

BOOTSTRAP := bootstrap

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

.PHONY: help setup wsl-usb run stop status doctor \
	_usb-status _run-gateway _run-backend _restart \
	_clear-all-history _clean _clean-dev \
	_ensure-dev-dirs _ensure-venv _ensure-history-dirs


#  User-facing commands


help:
	@echo "MINTS SCADA Software"
	@echo ""
	@echo "Linux:"
	@echo "  make setup"
	@echo "  make run"
	@echo ""
	@echo "WSL:"
	@echo "  make setup"
	@echo "  make wsl-usb"
	@echo "  make run"
	@echo ""
	@echo "Other commands:"
	@echo "  make stop     - Stop the application"
	@echo "  make status   - Show application status"


# Full setup: system deps + Python venv
setup:
	@bash $(BOOTSTRAP)/setup.sh


# WSL USB port forwarding setup (optional, WSL users only)
wsl-usb:
	@bash $(BOOTSTRAP)/wsl-usb.sh


# Start the application
run:
	@bash $(BOOTSTRAP)/run.sh


# Environment diagnostics
doctor:
	@bash $(BOOTSTRAP)/doctor.sh


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
	if [ -f "$(GATEWAY_PID_FILE)" ]; then \
		pid=$$(cat "$(GATEWAY_PID_FILE)" 2>/dev/null || true); \
		if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
			echo "[INFO] Stopping gateway pid=$$pid"; \
			kill "$$pid" 2>/dev/null || true; \
			sleep 1; \
			kill -0 "$$pid" 2>/dev/null && kill -9 "$$pid" 2>/dev/null || true; \
			stopped_any=1; \
		else \
			echo "[INFO] Gateway pid file exists but process is not alive"; \
		fi; \
	fi; \
	rm -f "$(GATEWAY_PID_FILE)" "$(GATEWAY_SOCKET)" "$(BACKEND_PID_FILE)" "$(BACKEND_SOCKET)" .shutdown_signal; \
	if [ "$$stopped_any" -eq 1 ]; then \
		echo "[OK] Application stopped"; \
	else \
		echo "[INFO] No running application processes found"; \
	fi


status:
	@echo "=== MINTS SCADA Status ==="
	@if [ -f "$(GATEWAY_PID_FILE)" ]; then \
		pid=$$(cat "$(GATEWAY_PID_FILE)" 2>/dev/null || true); \
		if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
			echo "Gateway PID: $$pid [alive]"; \
		else \
			echo "Gateway PID file exists but process is dead"; \
		fi; \
	else \
		echo "Gateway PID: [none]"; \
	fi
	@echo "Gateway socket: $(GATEWAY_SOCKET)"
	@if [ -S "$(GATEWAY_SOCKET)" ]; then echo "  [OK] socket exists"; else echo "  [--] socket missing"; fi
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


#  Development-only commands (not shown in help)


_usb-status:
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


_run-gateway:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Error: Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@mkdir -p "$(DEV_DIR)"
	@set -eu; \
	if [ -f "$(GATEWAY_PID_FILE)" ]; then \
		pid=$$(cat "$(GATEWAY_PID_FILE)" 2>/dev/null || true); \
		if [ -n "$$pid" ] && kill -0 "$$pid" 2>/dev/null; then \
			echo "[INFO] Gateway already running with pid=$$pid"; \
			exit 0; \
		else \
			echo "[INFO] Removing stale gateway pid file"; \
			rm -f "$(GATEWAY_PID_FILE)"; \
		fi; \
	fi; \
	if [ -S "$(GATEWAY_SOCKET)" ]; then \
		echo "[INFO] Removing stale gateway socket $(GATEWAY_SOCKET)"; \
		rm -f "$(GATEWAY_SOCKET)"; \
	fi; \
	echo "[INFO] Starting gateway..."; \
	nohup bash -lc 'source "$(VENV_ACTIVATE)" && exec $(PYTHON) $(GATEWAY)' >/dev/null 2>&1 & \
	echo $$! > "$(GATEWAY_PID_FILE)"; \
	echo "[INFO] Waiting for gateway socket $(GATEWAY_SOCKET)..."; \
	for i in $$(seq 1 80); do \
		if [ -S "$(GATEWAY_SOCKET)" ]; then \
			echo "[OK] Gateway started with pid=$$(cat "$(GATEWAY_PID_FILE)")"; \
			exit 0; \
		fi; \
		sleep 0.25; \
	done; \
	echo "[ERROR] Gateway socket did not appear."; \
	pid=$$(cat "$(GATEWAY_PID_FILE)" 2>/dev/null || true); \
	if [ -n "$$pid" ]; then kill "$$pid" 2>/dev/null || true; fi; \
	rm -f "$(GATEWAY_PID_FILE)" "$(GATEWAY_SOCKET)"; \
	exit 1


_run-backend:
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


_restart: stop run


_clear-all-history:
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


_clean: stop _clear-all-history
	@echo "[WARN] Removing local dev-only metadata and scratch directories..."
	@rm -f $(LOCAL_DEV_FILES)
	@rm -rf $(LOCAL_DEV_DIRS)
	@rm -rf "$(DEV_DIR)"
	@echo "[OK] Full dev cleanup complete"


_clean-dev:
	@echo "[INFO] Cleaning dev artifacts..."
	@rm -f "$(GATEWAY_PID_FILE)" "$(GATEWAY_SOCKET)" "$(BACKEND_PID_FILE)" "$(BACKEND_SOCKET)" "$(APPLICATION_PID_FILE)" .shutdown_signal
	@rmdir "$(DEV_DIR)" 2>/dev/null || true
	@echo "[OK] Dev artifacts cleaned"


#  Internal helpers


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
