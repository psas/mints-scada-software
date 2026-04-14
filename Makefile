# MINTS SCADA Software - Makefile
#
# Thin operator-facing entry layer. All implementation lives in bootstrap/.

SHELL := /bin/bash
BOOTSTRAP := bootstrap

.DEFAULT_GOAL := help

.PHONY: help setup wsl-usb run stop status doctor clean-history clean _clean-dev


help:
	@echo "MINTS SCADA Software"
	@echo ""
	@echo "  Setup:"
	@echo "    make setup          Check system deps, create venv, install deps"
	@echo "    make wsl-usb        Configure USB forwarding (WSL only)"
	@echo ""
	@echo "  Run:"
	@echo "    make run            Start the application"
	@echo "    make stop           Stop the application"
	@echo ""
	@echo "  Support:"
	@echo "    make status         Show application status"
	@echo "    make doctor         Check environment health"
	@echo ""
	@echo "  Cleanup (destructive, asks for confirmation):"
	@echo "    make clean-history  Delete all recording history data"
	@echo "    make clean          Full cleanup (stop + history + dev files)"


setup:
	@bash $(BOOTSTRAP)/setup.sh

wsl-usb:
	@bash $(BOOTSTRAP)/wsl-usb.sh

run:
	@bash $(BOOTSTRAP)/run.sh

stop:
	@bash $(BOOTSTRAP)/stop.sh

status:
	@bash $(BOOTSTRAP)/status.sh

doctor:
	@bash $(BOOTSTRAP)/doctor.sh

clean-history:
	@bash $(BOOTSTRAP)/clean-history.sh

clean:
	@bash $(BOOTSTRAP)/clean.sh


# Dev-only (not shown in help)

_clean-dev:
	@bash $(BOOTSTRAP)/clean-dev.sh
