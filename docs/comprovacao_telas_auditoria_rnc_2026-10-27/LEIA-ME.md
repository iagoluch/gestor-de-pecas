# Prova visual — telas de auditoria e decisão de RNC (27/10/2026)

Banco TEST (`gestor_pecas_test`, API :8002, conta `claude.teste`). Duas RNCs fictícias (RNC-PROVA-1 REFUGO, RNC-PROVA-2 RETRABALHO). O REAL não foi tocado.

1. `1-rnc-aviso-e-lista.jpg` — Qualidade > Decisão de RNC. Depois de decidir "Usar como está" numa peça REFUGO: aviso de contradição (a decisão foi gravada, não bloqueou) e a lista "Sem decisão" caiu de 2 para 1.
2. `2-rnc-formulario-e-historico.jpg` — formulário (Decisão + Justificativa) e histórico com "(vigente)", quem e quando.
3. `3-alteracoes-auditoria.jpg` — IagoDev > Alterações (só admin): a decisão da RNC aparece como "Decisão de RNC · RNC-PROVA-1 / Criou", junto das sugestões de manutenção anteriores.

## Eu fiz certo? Por quê?
- Sim no essencial: a decisão não bloqueia nada, o aviso aparece e a auditoria registra quem decidiu. Acesso: Qualidade e admin na decisão; só admin na auditoria (testes vitest e backend cobrem o 403).
- Ressalvas: (a) na auditoria o valor aparece cru ("usar_como_esta"), sem o rótulo humano; (b) em tela estreita a coluna "Mudança" precisa de rolagem horizontal; (c) o aviso usa tom "info", discreto — se a Qualidade não notar, vale destacar. Nenhuma bloqueia o uso.
