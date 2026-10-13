#!/bin/sh
# Mesmo comando do job "bandit" do CI (.github/workflows/ci.yml). Rode antes do push:
#   sh scripts/verificar_bandit.sh
# Sai com código != 0 se houver achado de severidade média/alta (ex.: B608).
cd "$(git rev-parse --show-toplevel)" || exit 1
for PY in ./.venv/Scripts/python.exe ./.venv/bin/python python python3; do
  if "$PY" -m bandit --version >/dev/null 2>&1; then
    exec "$PY" -m bandit -q -r backend mes app -ll
  fi
done
echo "bandit não instalado: pip install -r requirements-dev.txt" >&2
exit 2
