# DATABASE.md — Gestor de Peças

Extraído do `AGENTS.md` em 2026-09-29; tem a mesma força normativa do `AGENTS.md`.

## Fontes canônicas do backend

A UI não deve montar uma verdade paralela. Para novas implementações, usar preferencialmente:

- estado físico do recurso: `eventos_estado_recurso`;
- quantidade boa/refugo/retrabalho: `eventos_quantidade_producao`;
- execução de OP: `apontamentos_operacionais` + `eventos_apontamento_operador`;
- tempo físico/rateado: `sessoes_recurso` + `rateios_tempo_op`;
- calendário: `calendarios_produtivos`, `turnos_produtivos`, `intervalos_turno_produtivo`, `excecoes_calendario_produtivo`;
- Corte/Nesting: `apontamentos_corte`;
- rastreabilidade: fontes anteriores + participações de operador + referências de origem.

Fallback histórico pode existir para dados anteriores à fonte canônica, mas deve ser marcado explicitamente e não pode sobrescrever evidência física melhor.

## Consistência transacional e concorrência de dados

- operações produtivas relacionadas devem ser atômicas;
- proteger concorrência por recurso/OP quando necessário;
- não permitir duas sessões físicas sobrepostas do mesmo recurso;
- rateio deve conservar o tempo físico;
- migrations devem possuir espera limitada para locks;
- retries devem possuir limite;
- nunca limpar banco operacional em testes;
- testes PostgreSQL devem usar `TEST_DATABASE_URL` isolada; no workspace atual o banco TESTE oficial é `gestor_pecas_test`;
