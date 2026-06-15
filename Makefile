.PHONY: help install lint format test pre-commit clean

help:
	@echo "Available targets:"
	@echo "  install    - Install dev dependencies and pre-commit hooks"
	@echo "  lint       - Run ruff linter"
	@echo "  format     - Run ruff formatter"
	@echo "  test       - Run full test suite"
	@echo "  pre-commit - Run all pre-commit hooks on all files"
	@echo "  clean      - Remove build artifacts"

install:
	pip install -r requirements-dev.txt
	pre-commit install

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

test:
	pytest tests/ -v --tb=short

pre-commit:
	pre-commit run --all-files

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
