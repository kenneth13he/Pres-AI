#!/bin/zsh
set -eu
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  print 'Run setup_local.command first.'
  exit 1
fi
print 'PresAI voice check: http://127.0.0.1:8000/voice-check.html'
print 'Presentation room setup: http://127.0.0.1:8000/setup.html'
print 'Press Control-C to stop the local app.'
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
