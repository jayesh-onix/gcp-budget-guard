.PHONY: help lint isort black format run run-debug test deploy teardown login

SRC_DIR = src
TEST_DIR = tests

help:
	@echo ""
	@echo "GCP Budget Guard – available commands:"
	@echo "  make format    – Run isort + black on $(SRC_DIR)"
	@echo "  make lint      – Run pylint"
	@echo "  make test      – Run pytest"
	@echo "  make run       – Run locally (needs .env)"
	@echo "  make run-debug – Run locally in debug mode"
	@echo "  make deploy    – Deploy to GCP"
	@echo "  make teardown  – Remove all deployed GCP resources"
	@echo "  make login     – gcloud auth login"
	@echo ""

.DEFAULT_GOAL := help

isort:
	isort $(SRC_DIR)

black:
	black $(SRC_DIR)

format: isort black

lint: format
	pylint $(SRC_DIR)

test:
	PYTHONPATH=$(SRC_DIR) pytest $(TEST_DIR) -v --tb=short

run:
	@if [ -f .env ]; then set -a && . .env && set +a; fi && \
	PYTHONPATH=$(SRC_DIR) python $(SRC_DIR)/main.py

run-debug:
	@if [ -f .env ]; then set -a && . .env && set +a; fi && \
	DEBUG_MODE=1 PYTHONPATH=$(SRC_DIR) python $(SRC_DIR)/main.py

deploy:
	chmod +x deploy.sh && bash deploy.sh

teardown:
	chmod +x teardown.sh && bash teardown.sh

login:
	gcloud auth login && gcloud auth application-default login
