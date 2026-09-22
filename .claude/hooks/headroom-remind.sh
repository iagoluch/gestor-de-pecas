#!/usr/bin/env bash
# PostToolUse hook (Bash|Grep): se a saida da ferramenta for grande, forca um
# lembrete bloqueante para comprimir via headroom_compress antes de prosseguir.
input=$(cat)
len=$(printf '%s' "$input" | wc -c)
THRESHOLD=12000
if [ "$len" -gt "$THRESHOLD" ]; then
  printf '{"decision":"block","reason":"Saida desta ferramenta tem ~%s bytes (> %s). Antes de continuar, chame mcp__headroom__headroom_compress nesse conteudo (se for log/JSON estruturado) para economizar contexto; se o headroom classificar como router:noop, siga normalmente."}' "$len" "$THRESHOLD"
fi
exit 0
