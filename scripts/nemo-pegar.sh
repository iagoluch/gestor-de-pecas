#!/usr/bin/env bash
# Extrai o que o Nemotron mudou em ~/gestor (WSL) SEM fechar o OpenCode.
# Uso: scripts/nemo-pegar.sh [slug] [--reset]
#   slug     nome do patch (padrão: mmdd-hhmm) -> ../nemo-<slug>.patch
#   --reset  depois de extrair, devolve ~/gestor ao estado de origin/master (próxima tarefa limpa)
set -euo pipefail
export MSYS_NO_PATHCONV=1
reset=0; slug=$(date +%m%d-%H%M)
for a in "$@"; do if [ "$a" = "--reset" ]; then reset=1; else slug=$a; fi; done
repo="$(git rev-parse --show-toplevel)"
w() { wsl.exe -d Ubuntu-24.04 -u nemo -- "$@"; }

w bash -c 'cd ~/gestor && git add -A -- . ":!opencode.json" && git diff --cached --stat && git diff --cached --binary > /tmp/nemo-pegar.patch' | tr -d '\0\r'
w cat /tmp/nemo-pegar.patch > "$repo/../nemo-$slug.patch"
echo "[nemo-pegar] patch: $repo/../nemo-$slug.patch ($(wc -c < "$repo/../nemo-$slug.patch") bytes)"
if [ "$reset" = 1 ]; then
  w bash -c 'cd ~/gestor && git fetch -q origin master && git reset -q --hard origin/master && git clean -qfd && cp /tmp/nemo-tela.json opencode.json'
  echo "[nemo-pegar] ~/gestor resetado para origin/master"
fi
