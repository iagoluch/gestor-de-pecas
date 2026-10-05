#!/usr/bin/env bash
# SessionStart(compact): re-injeta estado verificável do repo após a compactação.
# Local e determinístico: só git; nada sai da máquina e o transcript não é tocado.
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0

echo "Contexto foi compactado. Estado atual do repo (lido agora, não do resumo):"
echo "Branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
echo "Últimos commits:"
git log --oneline -5 2>/dev/null
echo "Alterações não commitadas (máx. 25 linhas):"
git status --short 2>/dev/null | head -25
echo "Diff stat:"
git diff --stat 2>/dev/null | tail -15
echo "O resumo da compactação pode ter perdido caminhos, erros exatos e resultados de teste."
echo "Antes de afirmar que algo passou/falhou ou editar um arquivo, releia a fonte ou rode a validação de novo."
exit 0
