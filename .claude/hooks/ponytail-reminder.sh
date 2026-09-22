#!/usr/bin/env bash
# UserPromptSubmit hook: injeta lembrete da skill ponytail em todo prompt do usuario.
# Nao bloqueia nada; so garante que a instrucao chegue mesmo que a memoria nao seja lida.
cat >/dev/null
echo "Lembrete automatico (hook, nao memoria): se este prompt envolver escrever/alterar/revisar codigo, aplique a skill 'ponytail' (Skill({skill:\"ponytail\"})) - solucao mais simples e minima que funciona, YAGNI, sem over-engineering. Ignorar se o prompt nao for sobre codigo."
exit 0
