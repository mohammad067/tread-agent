# Market State Engine — developer task runner.
# Note: `make` may not be installed on all dev machines (Windows). Each target maps to a
# plain `python -m ...` command you can run directly; this file is the documented contract.

.PHONY: install lint format typecheck test contract golden coverage imports check

install:
	python -m pip install -e ".[dev]"

lint:
	python -m ruff check src tests

format:
	python -m ruff format --check src tests

typecheck:
	python -m mypy

test:
	python -m pytest

contract:
	python -m pytest -m contract

golden:
	python -m pytest -m golden

coverage:
	python -m pytest --cov --cov-report=term-missing

imports:
	lint-imports

# Full local gate — mirrors CI.
check: lint format typecheck imports coverage
