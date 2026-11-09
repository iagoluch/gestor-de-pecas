# Codex como revisor externo (chamado pelo Claude)

Papel: segunda opinião independente, **somente leitura**. Nunca edita código, nunca toca em banco/Protheus/dados REAL.

## Quando usar
- Toda tarefa **não pequena** que cria/altera código (regra do usuário, 09/11/2026; critério de "pequena" no CLAUDE.md), depois dos testes e antes de entregar.
- Bug difícil sem causa após 1 tentativa do Claude (pedir hipóteses, não correção).
- Sem diff de código (só docs): não aplicável.

## Como chamar
```powershell
powershell -File scripts\codex_revisor.ps1 -Tarefa "Revise por bugs e regressões"
powershell -File scripts\codex_revisor.ps1 -Tarefa "..." -Arquivos a.py,b.py   # só estes arquivos
powershell -File scripts\codex_revisor.ps1 -Tarefa "..." -Base HEAD~1         # último commit
```
O script envia o diff pelo stdin (Codex não gasta passos lendo), esforço `low`, sem resumo de
raciocínio, sessão efêmera, `CODEX_HOME=~\.codex-lean` (sem plugins/MCP/hooks/AGENTS global) e
`project_doc_max_bytes=0` (não carrega o AGENTS.md de 31 KB). Use `-Esforco high` só em R3.

## Regras
- Claude confere cada achado antes de agir (Codex pode errar); achado confirmado vira correção feita pelo Claude.
- Um editor por vez nos mesmos arquivos: Codex não edita enquanto o Claude trabalha.
- `~\.codex-lean\auth.json` é cópia do login; se o login do Codex mudar, recopie de `~\.codex\auth.json`.
- Medição (09/11/2026): piso do próprio Codex ≈ 14,7 mil tokens por chamada (prompt e ferramentas embutidos; instrução customizada, desligar ferramentas e esconder skills não mudaram nada). Acima disso só o diff. Sem o modo enxuto: ≈ 26 mil.
- Economia real = menos chamadas: junte vários pontos em UMA chamada (diff maior), e use só em R2/R3.
