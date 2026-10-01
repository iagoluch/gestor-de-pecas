# Auditoria fullstack — estado (2026-10-01)

> Retomada após compactação: ler este arquivo, `git log -5`, `git status`, e os logs `_*.log` desta pasta.

## Restrição operacional da sessão
Orçamento semanal do Claude em 93% (reseta 03/10 23:59). A varredura foi **fatiada por valor**: prioridade para
(1) provar os 11 pontos de regressão conhecidos, (2) baseline de build/typecheck/testes, (3) inventário mecânico via
Nemotron 3 Ultra (Goose CLI, somente leitura). E2E humanizado com vídeo, galeria HTML e passada de qualidade
**não cabem no orçamento restante** — ver "Pendências".

## Matriz dos 11 pontos (HEAD 9d54e11 já os implementou; aqui está a prova por teste executado)
| # | Ponto | Prova executada | Status |
|---|---|---|---|
| 1 | Tempo padrão do Protheus (0,01 = não configurado) | `tests/` (mapper/parser TOTVS) na suíte completa | PASS (suíte completa 1472 verdes) |
| 2 | Múltiplas ordens dividem o tempo | `test_concurrent_resource_production.py` (verde) + `_concurrent_production_seconds` | PASS |
| 3 | Fila da Solda por estação (409 em outra estação) | `test_totvs_operator_queue.py` (verde) | PASS |
| 4 | Parada após selecionar tarefa | `operator.test.tsx` "Destaque: Parada segue disponível…" (verde) | PASS |
| 5 | Desselecionar recolhe | idem (clicar de novo desseleciona) | PASS |
| 6 | Chamadas Iago Dev × Gestão | `management.test.tsx` (verde) | PASS |
| 7 | Sem nomes brutos na UI | `display-names.test.tsx` (verde) | PASS |
| 8 | IA sem dado bruto | `mes/services/ai_presentation.py` + testes de IA na suíte completa | PASS (suíte completa 1472 verdes) |
| 9 | Filtro de pausas | `pauses.test.tsx` (verde) | PASS |
| 10 | Aba Metas oculta | `management.test.tsx` (verde) | PASS |
| 11 | Telegram (fluxo/auditoria) | testes de Telegram na suíte completa | PASS (suíte completa 1472 verdes) |

## Achados e correções desta sessão
1. **Guarda anti-N+1 do `insights` falhava (3 > 2 consultas de fatos)** — causa-raiz: o rateio de OPs simultâneas
   (`IndustrialAnalyticsService._concurrent_production_seconds`) faz 1 consulta larga adicional (necessária: as OPs que
   dividem o recurso podem estar fora do filtro; recurso comparado por identidade canônica em Python). Custo constante,
   não N+1. Teste ajustado para ≤3 com justificativa e a asserção de filtro passou a aceitar a consulta larga sem `recurso`
   (mantém `setor`). Arquivo: `tests/test_management_insights.py`.
2. **`operator.test.tsx › mede a cota…` flaky sob carga** — assert com `waitFor` no timeout padrão (1000 ms) estourava com
   pytest rodando em paralelo; passa 3/3 isolado. Correção: `asyncUtilTimeout: 4000` em `web/src/test/setup.ts`
   (falha continua real se a UI nunca chegar ao estado).

## Evidências
Logs brutos: `_py_targeted.log`, `_py_full.log`, `_web_build.log`, `_vitest_targeted.log`, `_vitest_full.log`.
Nemotron 3 Ultra (Goose CLI: `dist-windows/resources/bin/goose.exe run -i -`, em `C:/Program Files (x86)`) foi acionado para o inventário de dívida
técnica e caiu com `Stream decode error` (rede) antes de gravar; o inventário foi refeito via ripgrep: **0** TODO/FIXME/HACK,
**0** `except:` nu, **0** `except Exception: pass`, **0** `any` em produção, 2 `print` só em CLIs (bootstrap_admin, seed_dev).
Nota: a extensão `claude-sync:headroom` falha ao iniciar no Goose (incompatibilidade de handshake MCP `server/discover`) — não bloqueia.

## Resultados reais
- `python -m pytest tests --ignore=tests/test_e2e_smoke.py`: **1472 passed, 1 skipped, exit 0** (621 s). Skips = testes Postgres sem `TEST_DATABASE_URL`
  (invariantes de concorrência em banco real **não** exercitadas nesta sessão).
- `npm run build` (tsc -b + vite): exit 0. `tsc -b --noEmit`: exit 0.
- `vitest run`: **20 arquivos, 258 passed** (após o ajuste de timing).
- E2E smoke Playwright (`tests/test_e2e_smoke.py`, preview self-contained): **1 passed**.
- Lint: não há script `lint` no `web/package.json`; Python usa bandit/pip-audit só no CI (não rodados aqui).

## Pendências reais (não feitas por limite de orçamento, não por bloqueio técnico)
- E2E Playwright humanizado (apontamento completo, múltiplas ordens, pausa/retorno) com vídeo/trace + galeria HTML.
- Passada de qualidade (código morto/duplicação) e auditoria linha-a-linha de backend/segurança além do que a suíte cobre.
- Invariantes de concorrência em Postgres real (`TEST_DATABASE_URL`) e lint/bandit/pip-audit locais.
