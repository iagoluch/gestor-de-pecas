#!/bin/sh
# Setup idempotente dos git hooks de desenvolvimento deste repositório.
# Rode uma vez por clone: `sh scripts/setup-dev-hooks.sh`
#
# Não sobrescreve nada que já exista no post-commit — só garante que a
# chamada ao script versionado (scripts/graphify-rebuild.sh) esteja lá.
set -e
ROOT="$(git rev-parse --show-toplevel)"
HOOK="$ROOT/.git/hooks/post-commit"
MARKER='scripts/graphify-rebuild.sh'

if [ ! -f "$HOOK" ]; then
  printf '#!/bin/sh\n' > "$HOOK"
fi

if ! grep -q "$MARKER" "$HOOK" 2>/dev/null; then
  printf '\n. "%s/%s"\n' '$(git rev-parse --show-toplevel)' "$MARKER" >> "$HOOK"
  echo "post-commit: adicionado o gatilho do graphify-rebuild."
else
  echo "post-commit: gatilho do graphify-rebuild já estava instalado, nada a fazer."
fi

chmod +x "$HOOK"
echo "Pronto. O grafo do graphify passa a se atualizar sozinho a cada commit que tocar mes/backend/app/web/tests."

# pre-push: bandit local antes de subir (o CI barra o mesmo achado, ~10 s aqui vs ~10 min lá).
PUSH_HOOK="$ROOT/.git/hooks/pre-push"
PUSH_MARKER='scripts/pre-push-bandit.sh'
[ -f "$PUSH_HOOK" ] || printf '#!/bin/sh
' > "$PUSH_HOOK"
if ! grep -q "$PUSH_MARKER" "$PUSH_HOOK" 2>/dev/null; then
  printf '
sh "$(git rev-parse --show-toplevel)/%s" || exit 1
' "$PUSH_MARKER" >> "$PUSH_HOOK"
  echo "pre-push: adicionado o gatilho do bandit."
else
  echo "pre-push: gatilho do bandit já estava instalado, nada a fazer."
fi
chmod +x "$PUSH_HOOK"
