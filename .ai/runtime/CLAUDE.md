# Claude runtime

Orquestrador alvo: **Claude Opus 5.5 / high**.

- `.claude/settings.json` fixa effort high.
- Funcionários: `.claude/agents/`.
- Skills: `.claude/skills/`.
- Context7: `.mcp.json`.
- Agentes críticos usam `opus`; execução comum usa `sonnet`.
- Iago deve selecionar Opus 5.5 no app/CLI se o alias local `opus` apontar para outra versão.
