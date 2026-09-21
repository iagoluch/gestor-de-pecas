#!/usr/bin/env bash
# SessionStart hook: garante que o servidor local do omniroute (127.0.0.1:20128)
# esteja no ar antes da sessao comecar a usar o MCP. Best-effort: nunca bloqueia
# a sessao se o omniroute nao estiver instalado ou a porta nao subir a tempo.
set -u

PORT=20128
RUN_DIR="$HOME/.omniroute-run"

if command -v netstat >/dev/null 2>&1 && netstat -ano 2>/dev/null | grep -qi "127\.0\.0\.1:$PORT.*LISTENING"; then
  exit 0
fi

if ! command -v omniroute >/dev/null 2>&1; then
  exit 0
fi

mkdir -p "$RUN_DIR"
(
  cd "$RUN_DIR" || exit 0
  OMNIROUTE_SERVER_HOST=127.0.0.1 nohup omniroute serve >> omniroute_serve.log 2>&1 &
  disown
)
exit 0
