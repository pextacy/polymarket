.PHONY: install bootstrap-stack dev-up dev-up-core dev-down pull-model wait-services docker-build docker-scan docker-paper-trade-once scan paper-trade-once paper-trade test

PYTHON ?= python3.11

install:
	$(PYTHON) -m pip install -e ".[dev]"

bootstrap-stack:
	./scripts/bootstrap_oss_stack.sh

dev-up:
	./scripts/dev_up.sh

dev-up-core:
	./scripts/dev_up.sh --core

dev-down:
	./scripts/dev_down.sh

pull-model:
	./scripts/pull_ollama_model.sh

wait-services:
	./scripts/wait_for_services.sh

docker-build:
	docker compose build trader

docker-scan:
	docker compose run --rm trader polymarket scan --top 10

docker-paper-trade-once:
	docker compose run --rm trader polymarket paper-trade --once

scan:
	$(PYTHON) -m polymarket_trader.cli scan --top 10

paper-trade-once:
	$(PYTHON) -m polymarket_trader.cli paper-trade --once

paper-trade:
	$(PYTHON) -m polymarket_trader.cli paper-trade

test:
	PYTHONPATH=src $(PYTHON) -m pytest tests/ -v
