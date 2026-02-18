.PHONY: install test run docker-build docker-run clean format lint install-hooks

install:
	pip install -r requirements.txt

test:
	@echo "Running basic validation..."
	@python -c "import src.config; print('Config module OK')"
	@python -c "import src.models; print('Models module OK')"
	@python -c "import src.parser; print('Parser module OK')"
	@python -c "import src.scraper; print('Scraper module OK')"
	@python -c "import src.database; print('Database module OK')"
	@python -c "import src.email; print('Email module OK')"
	@python -c "import src.main; print('Main module OK')"
	@echo "All modules validated successfully"

run:
	python -m src.main; exit_code=$$?; \
	if [ $$exit_code -eq 2 ]; then \
		echo "No new messages (already processed) - this is expected"; \
		exit 0; \
	fi; \
	exit $$exit_code

docker-build:
	docker build -t unofficial-homecase-automation .

docker-run:
	docker run --rm --env-file .env unofficial-homecase-automation

format:
	@echo "Formatting code with black..."
	@pip install -q black || pip install black
	black src/

lint:
	@echo "Linting code with ruff..."
	@pip install -q ruff || pip install ruff
	ruff check src/

clean:
	find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -r {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -r {} + 2>/dev/null || true

install-hooks:
	@echo "Installing pre-commit hook..."
	@bash scripts/install-pre-commit-hook.sh
