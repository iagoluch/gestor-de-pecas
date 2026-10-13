#!/bin/sh
# Gatilho do hook pre-push: roda o bandit (~10 s, igual ao CI) e só mostra saída se falhar.
OUT=$(sh "$(git rev-parse --show-toplevel)/scripts/verificar_bandit.sh" 2>&1)
RC=$?
if [ "$RC" -ne 0 ]; then
  echo "$OUT" | grep -v "^\[manager\]\|^\[tester\]\|^\[main\]" | tail -40
  echo "push recusado: bandit falhou (corrija ou justifique com # nosec Bxxx -- motivo). Para ignorar: git push --no-verify" >&2
  exit 1
fi
