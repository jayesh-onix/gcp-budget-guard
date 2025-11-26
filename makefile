.PHONY: help lint isort run

SRC_DIR=src
SCRIPTS_DIR=scripts

help:
	@echo ""
	@echo "Available commands:"
	@echo "  make isort    - Run isort on $(SRC_DIR)"
	@echo "  make black    - Run black on $(SRC_DIR)"
	@echo "  make lint     - Run isort + flake8 on $(SRC_DIR)"
	@echo "  make login    - Run gcloud auth application-default login"
	@echo "  make run      - Run main.py"
	@echo "  make build    - Run build Docker (contributors only)"
	@echo ""

default: help
.DEFAULT_GOAL := default

isort:
	isort $(SRC_DIR)/*

black:
	black $(SRC_DIR)/*

lint: isort black
	pylint $(SRC_DIR)/*

login:
	gcloud auth login && gcloud auth application-default login

run:
	$(shell grep -v '^#' .env | xargs) python $(SRC_DIR)/main.py

rundebug:
	$(shell grep -v '^#' .env | xargs) DEBUG_MODE=1 python $(SRC_DIR)/main.py


build:
	echo ""