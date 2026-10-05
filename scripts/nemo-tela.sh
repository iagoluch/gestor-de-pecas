#!/usr/bin/env bash
# Roda DENTRO do WSL (user nemo). Branch master (reset p/ origin/master) + OpenCode com interface (TUI).
# Ao sair do OpenCode, gera /tmp/nemo-tela.patch com tudo que ele mudou.
set -euo pipefail
export PATH=$HOME/.npm-global/bin:$HOME/.local/bin:$PATH
repo=$HOME/gestor; slug=tela-$(date +%m%d-%H%M)
cd "$repo"
git fetch -q origin master
git checkout -q master
if [ -n "$(git status --porcelain)" ]; then  # sobra de sessão anterior: guarda antes de limpar
  git add -A -- . ':!opencode.json'
  git diff --cached --binary > "/tmp/nemo-tela-anterior-$slug.patch"
  echo "[nemo-tela] sobras da sessão anterior salvas em /tmp/nemo-tela-anterior-$slug.patch"
fi
git reset -q --hard origin/master && git clean -qfd
cp /tmp/nemo-tela.json opencode.json
echo "[nemo-tela] $repo na branch master (= origin/master)"; echo "[nemo-tela] A interface leva ~30 s para aparecer (tela preta é normal): carregando MCPs. Depois cole o prompt do Claude."
${NEMO_CMD:-opencode}
git add -A -- . ':!opencode.json'
git diff --cached --stat
git diff --cached --binary > /tmp/nemo-tela.patch
echo "$slug" > /tmp/nemo-tela.slug
