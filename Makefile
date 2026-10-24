.PHONY: setup dev check lint type test schema schema-check mocks clean

PY ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn

setup:            ## one-time: create .venv and install pinned deps
	uv venv .venv --python 3.12 || python3 -m venv .venv
	uv pip install --python $(PY) -r requirements.txt || $(PY) -m pip install -r requirements.txt
	cp -n .env.example .env || true
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
