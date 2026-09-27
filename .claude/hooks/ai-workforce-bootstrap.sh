#!/usr/bin/env bash
set -u
if command -v python >/dev/null 2>&1; then
  python scripts/validate_ai_workforce.py --quiet >/dev/null 2>&1 || {
    echo "AI Workforce invalida; rode python scripts/validate_ai_workforce.py"
    exit 0
  }
fi
echo "AI Workforce ativa: .ai/ORCHESTRATOR.md; delegue somente quando o risco justificar."
