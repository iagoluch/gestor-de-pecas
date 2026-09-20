#!/bin/sh
# Rebuild the graphify knowledge graph after each commit (background, non-blocking).
# Scope: mes, backend, app, web, tests (code-only, AST-based, no LLM calls).
# Regenerated whenever this project's commit touches those folders.
#
# Versionado (ao contrário de .git/hooks/, que não viaja com o clone) — ver
# scripts/setup-dev-hooks.sh para instalar o gatilho de post-commit.
LOG="$HOME/.cache/graphify-rebuild.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null
{
  echo "=== graphify rebuild $(date) ==="
  cd "$(git rev-parse --show-toplevel)" || exit 0
  changed=$(git diff --name-only HEAD~1 HEAD 2>/dev/null)
  needs_rebuild=0
  for d in mes backend app web tests; do
    if echo "$changed" | grep -q "^$d/"; then
      needs_rebuild=1
    fi
  done
  if [ "$needs_rebuild" = "0" ]; then
    echo "No changes under mes/backend/app/web/tests - skipping rebuild."
    exit 0
  fi
  if ! command -v graphify >/dev/null 2>&1; then
    echo "graphify não está no PATH - pulando rebuild (instale com 'uv tool install graphifyy')."
    exit 0
  fi
  graphify extract ./mes/ --code-only
  graphify extract ./backend/ --code-only
  graphify extract ./app/ --code-only
  graphify extract ./web/ --code-only
  graphify extract ./tests/ --code-only
  graphify merge-graphs ./mes/graphify-out/graph.json ./backend/graphify-out/graph.json ./app/graphify-out/graph.json ./web/graphify-out/graph.json ./tests/graphify-out/graph.json --out graphify-out/graph.json
  graphify cluster-only .
  echo "=== graphify rebuild done $(date) ==="
} >> "$LOG" 2>&1 &
disown 2>/dev/null
exit 0
