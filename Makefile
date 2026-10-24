.PHONY: setup dev check lint type test schema schema-check mocks clean

PY ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn

setup:            ## one-time: create .venv and install pinned deps
	@set -eu; \
	if command -v uv >/dev/null 2>&1; then \
		uv venv .venv --python 3.12; \
	else \
		setup_python=""; \
		if command -v python3.12 >/dev/null 2>&1; then setup_python=python3.12; \
		elif command -v python3 >/dev/null 2>&1; then setup_python=python3; fi; \
		if [ -z "$$setup_python" ] || ! "$$setup_python" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))'; then \
			printf '%s\n' 'Python 3.12 or newer is required. Install Python 3.12 or uv before make setup.'; \
			exit 1; \
		fi; \
		"$$setup_python" -m venv .venv; \
	fi
	cp -n .env.example .env || true
	chmod 600 .env
	uv pip install --python $(PY) -r requirements.txt || $(PY) -m pip install -r requirements.txt
	$(MAKE) schema

dev:              ## run the app (API + frontend) on $$PORT (default 8000)
	$(UVICORN) backend.main:app --reload --port $${PORT:-8000}

check: lint type schema-check mocks test   ## the gate: exit 0 or it does not merge

lint:
	$(PY) -m ruff check backend spec scripts

type:
	$(PY) -m pyright backend spec scripts

schema:           ## regenerate spec/contracts.schema.json from spec/contracts.py
	$(PY) scripts/gen_schema.py

schema-check:
	$(PY) scripts/gen_schema.py --check

mocks:            ## validate frontend/mocks/*.json against the contracts
	$(PY) scripts/check_mocks.py

test:
	$(PY) -m pytest backend/tests -q

clean:
	rm -rf .venv .pytest_cache .ruff_cache
