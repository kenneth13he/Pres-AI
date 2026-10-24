#!/bin/zsh
set -eu
cd "${0:A:h}"
if ! command -v node >/dev/null 2>&1; then
  bundled_node="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"
  if [[ -x "$bundled_node/node" ]]; then
    export PATH="$PATH:$bundled_node"
  else
    print 'Node.js is required for the frontend checks. Install Node.js, then run setup again.'
    exit 1
  fi
fi
if [[ "$(node --help 2>/dev/null)" != *'--test-timeout'* ]]; then
  print 'Node.js must support --test-timeout. Update Node.js, then run setup again.'
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv --python 3.12
  elif command -v python3.12 >/dev/null 2>&1; then
    python3.12 -m venv .venv
  elif [[ -x "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" ]]; then
    "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" -m venv .venv
  else
    print 'Python 3.12 is required. Install it or uv, then run this setup again.'
    exit 1
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python -r requirements.txt
else
  .venv/bin/python -m pip install -r requirements.txt
fi
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
fi
make check
node --test --test-timeout=5000 scripts/test_*.mjs
print '\nSetup complete. Run start_local.command, then open http://127.0.0.1:8000/setup.html'
