#!/usr/bin/env bash
# Delega uma tarefa ao Nemotron (OpenCode) rodando no WSL (Ubuntu-24.04, user nemo), isolado do Windows.
# Uso: scripts/nemo.sh <slug> <arquivo-do-prompt> [modelo]   (modelo: ultra [padrão] | super | kimi | glm | gemma | id completo; ver .ai/NEMO_MODELOS.md)
# Ele trabalha num worktree de origin/master do clone ~/gestor do WSL (sem .env, sem untracked do Windows).
# Resultado: patch em ../nemo-<slug>.patch; aplicar com `git apply ../nemo-<slug>.patch` após revisar.
set -euo pipefail
export MSYS_NO_PATHCONV=1
slug="${1:?slug}"; prompt_file="${2:?arquivo do prompt}"
repo="$(git rev-parse --show-toplevel)"
w() { wsl.exe -d Ubuntu-24.04 -u nemo -- "$@"; }

case "${3:-ultra}" in
  ultra) model=opencode/nemotron-3-ultra-free ;;
  super) model=nvidia/nvidia/nemotron-3-super-120b-a12b ;;
  kimi)  model=nvidia/moonshotai/kimi-k3 ;;
  glm)   model=nvidia/z-ai/glm-5.3 ;;
  gemma) model=nvidia/google/gemma-4-31b-it ;;
  *)     model=$3 ;;
esac

# feed do painel scripts/nemo-hub.html: eventos em ../nemo-runs.js (fora do repo); o EXIT fecha a run mesmo se algo abortar
runs="$repo/../nemo-runs.js"; id="$slug-$(date +%s)"; t0=$(date +%s); state=erro; bytes=0
ev() { [ -f "$runs" ] || echo 'window.NEMO_LIVE=[];' > "$runs"; echo "NEMO_LIVE.push({id:\"$id\",slug:\"$slug\",model:\"$model\",$1});" >> "$runs"; }
ev "state:\"running\",t0:$t0"
trap 'ev "state:\"$state\",secs:$(( $(date +%s) - t0 )),bytes:$bytes"' EXIT
log=$(mktemp)

# entrega prompt e permissões (opencode.json local, possivelmente ainda não commitado) ao WSL
w bash -c "cat > /tmp/nemo-$slug.prompt" < "$prompt_file"
w bash -c "cat > /tmp/nemo-$slug.json" < "$repo/opencode.json"

w bash -s "$slug" "$model" <<'EOS' | tr -d '\r' | tee "$log"
set -euo pipefail
export PATH=$HOME/.npm-global/bin:$HOME/.local/bin:$PATH
slug=$1; model=$2; repo=$HOME/gestor; wt=$HOME/nemo-$slug
git -C "$repo" fetch -q origin master
git -C "$repo" worktree add -q "$wt" -b "nemo/$slug" origin/master
cp "/tmp/nemo-$slug.json" "$wt/opencode.json"
cd "$wt"
timeout 900 opencode run --auto --model "$model" "$(cat "/tmp/nemo-$slug.prompt")" < /dev/null || echo "[nemo] opencode saiu com erro/timeout: $?"
git add -A -- . ':!opencode.json'
echo "=== git diff --stat ($wt) ==="
git diff --cached --stat
git diff --cached --binary > "/tmp/nemo-$slug.patch"
EOS

w cat "/tmp/nemo-$slug.patch" > "$repo/../nemo-$slug.patch"
bytes=$(wc -c < "$repo/../nemo-$slug.patch")
if grep -q 'erro/timeout: 124' "$log"; then state=timeout; elif grep -q 'saiu com erro' "$log"; then state=erro; elif [ "$bytes" -eq 0 ]; then state=vazio; else state=ok; fi
rm -f "$log"
echo "[nemo] patch: $repo/../nemo-$slug.patch ($bytes bytes) — revise e aplique com: git apply ../nemo-$slug.patch"
