# IA Workforce — Gestor de Peças

Organização **privada de engenharia por IA** usada apenas por Iago no desenvolvimento. Não faz parte do produto: não cria API, tabela, tela ou funcionalidade MES.

## Runtime
- Claude Code/Desktop Code: orquestrador = **Claude Opus 5.5 / high**.
- Codex: orquestrador = **GPT-5.6 Sol (`gpt-5.6`) / high**.
- Especialistas usam contexto isolado e podem usar modelos menores em tarefas operacionais; funções críticas usam classe flagship/high.
- Se o runtime não suportar modelo distinto por subagente, herdar o modelo do orquestrador.

## Fluxo
1. Iago entrega o objetivo ao orquestrador.
2. O orquestrador classifica domínio e risco.
3. Seleciona somente os especialistas necessários.
4. Cada especialista recebe contexto mínimo e definição de pronto.
5. QA/reviewer entram conforme risco.
6. O orquestrador integra e responde uma única vez.

Leia: `.ai/ORCHESTRATOR.md` → `.ai/GOVERNANCE.md` → `.ai/TOOLING.md` → perfil em `.ai/employees/`.

Fonte machine-readable: `.ai/organization.json`.

**Regra de ouro:** aumentar qualidade com menos contexto; não simular burocracia.
