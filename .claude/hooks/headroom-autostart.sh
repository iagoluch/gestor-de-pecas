#!/usr/bin/env bash
# SessionStart hook: garante que o proxy local do headroom (127.0.0.1:8787)
# esteja no ar antes da sessao comecar a usar o MCP. Best-effort: nunca bloqueia
# a sessao se o headroom nao estiver instalado ou a porta nao subir a tempo.
set -u
PORT=8787
RUN_DIR="$HOME/.headroom-run"
if command -v netstat >/dev/null 2>&1 && netstat -ano 2>/dev/null | grep -qi "127\.0\.0\.1:$PORT.*LISTENING"; then
  exit 0
fi
if ! command -v headroom >/dev/null 2>&1; then
  exit 0
fi
mkdir -p "$RUN_DIR"
(
  cd "$RUN_DIR" || exit 0
  nohup headroom proxy >> headroom_proxy.log 2>&1 &
  disown
)
exit 0
