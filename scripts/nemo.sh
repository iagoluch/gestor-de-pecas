#!/usr/bin/env bash
# Delega uma tarefa ao Nemotron (OpenCode) rodando no WSL (Ubuntu-24.04, user nemo), isolado do Windows.
# Uso: scripts/nemo.sh <slug> <arquivo-do-prompt> [modelo]   (modelo: ultra [padrão] | super | kimi | id completo; ver .ai/NEMO_MODELOS.md)
# Ele trabalha num worktree de origin/master do clone ~/gestor do WSL (sem .env, sem untracked do Windows).
# Resultado: patch em ../nemo-<slug>.patch; aplicar com `git apply ../nemo-<slug>.patch` após revisar.
set -euo pipefail
export MSYS_NO_PATHCONV=1
slug="${1:?slug}"; prompt_file="${2:?arquivo do prompt}"
[[ $slug =~ ^[a-z0-9-]{1,48}$ ]] || { echo "[nemo] slug inválido (a-z, 0-9, hífen, até 48): $slug" >&2; exit 2; }
repo="$(git rev-parse --show-toplevel)"
w() { wsl.exe -d Ubuntu-24.04 -u nemo -- "$@"; }

case "${3:-ultra}" in
  ultra) model=opencode/nemotron-3-ultra-free ;;
  super) model=nvidia/nvidia/nemotron-3-super-120b-a12b ;;
  kimi)  model=nvidia/moonshotai/kimi-k3 ;;
  *)     model=$3 ;;
esac

# feed do painel scripts/nemo-hub.py: eventos JSON em ../nemo-runs.js e log ao vivo em ../nemo-logs/<id>.log (fora do repo); o EXIT fecha a run mesmo se algo abortar
runs="$repo/../nemo-runs.js"; id="${NEMO_RUN_ID:-$slug-$(date +%s)}"; t0=$(date +%s); state=erro; bytes=0
[[ $id =~ ^[a-z0-9-]{1,64}$ ]] || { echo "[nemo] NEMO_RUN_ID inválido: $id" >&2; exit 2; }
ev() { [ -f "$runs" ] || echo 'window.NEMO_LIVE=[];' > "$runs"; echo "NEMO_LIVE.push({\"id\":\"$id\",\"slug\":\"$slug\",\"model\":\"$model\",$1});" >> "$runs"; }
ev "\"state\":\"running\",\"t0\":$t0"
trap 'ev "\"state\":\"$state\",\"secs\":$(( $(date +%s) - t0 )),\"bytes\":$bytes"' EXIT
mkdir -p "$repo/../nemo-logs"; log="$repo/../nemo-logs/$id.log"

# entrega prompt e permissões (opencode.json local, possivelmente ainda não commitado) ao WSL
# o AGENTS.md global do WSL traz as regras do orquestrador (handoff/Roteamento:); sem este aviso o worker devolve um prompt em vez de executar (visto em 06/10/2026)
exec_note='[EXECUTOR] Você é o worker que EXECUTA esta tarefa neste worktree, não o orquestrador. Ignore as regras globais de roteamento, o handoff para o Nemotron e o rodapé "Roteamento:". Não devolva prompt nem plano: edite os arquivos, rode a validação e mostre o git diff --stat.'
{ printf '%s\n\n' "$exec_note"; cat "$prompt_file"; } | w bash -c "cat > /tmp/nemo-$slug.prompt"
w bash -c "cat > /tmp/nemo-$slug.json" < "$repo/opencode.json"

w bash -s "$slug" "$model" 2>&1 <<'EOS' | sed -u 's/\r$//' | tee "$log"
set -euo pipefail
export PATH=$HOME/.npm-global/bin:$HOME/.local/bin:$PATH
slug=$1; model=$2; repo=$HOME/gestor; wt=$HOME/nemo-$slug
git -C "$repo" fetch -q origin master
git -C "$repo" worktree add -q "$wt" -b "nemo/$slug" origin/master
cp "/tmp/nemo-$slug.json" "$wt/opencode.json"
cd "$wt"
# cancelado pelo painel durante fetch/worktree add (ainda não havia processo para encerrar): não chama o modelo
if [ -e "$HOME/nemo-$slug.cancel" ]; then
  echo "[nemo] cancelado antes de iniciar"; : > "/tmp/nemo-$slug.patch"; rm -f "$HOME/nemo-$slug.cancel"; exit 0
fi
timeout 900 opencode run --auto --model "$model" "$(cat "/tmp/nemo-$slug.prompt")" < /dev/null || echo "[nemo] opencode saiu com erro/timeout: $?"
git add -A -- . ':!opencode.json'
echo "=== git diff --stat ($wt) ==="
git diff --cached --stat
git diff --cached --binary > "/tmp/nemo-$slug.patch"
rm -f "$HOME/nemo-$slug.cancel"
EOS

w cat "/tmp/nemo-$slug.patch" > "$repo/../nemo-$slug.patch"
bytes=$(wc -c < "$repo/../nemo-$slug.patch")
# linhas do próprio runner, ancoradas: o texto do modelo no log não pode mudar o estado
if grep -qx '\[nemo\] opencode saiu com erro/timeout: 124' "$log"; then state=timeout
elif grep -qxE '\[nemo\] opencode saiu com erro/timeout: (137|143)' "$log"; then state=cancelado
elif grep -qE '^\[nemo\] opencode saiu com erro' "$log"; then state=erro
elif [ "$bytes" -eq 0 ]; then state=vazio; else state=ok; fi
[ -e "$repo/../nemo-logs/$id.cancel" ] && state=cancelado  # marcador do painel: o opencode sai com 1 ao receber TERM, indistinguível de erro
echo "[nemo] patch: $repo/../nemo-$slug.patch ($bytes bytes) — revise e aplique com: git apply ../nemo-$slug.patch"
