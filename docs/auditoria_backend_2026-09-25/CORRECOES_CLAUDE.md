# Correções da auditoria de backend — execução Claude (29/09/2026)

**Fonte canônica:** `RELATORIO_CLAUDE_2026-09-29.md` (BK-01..BK-26). Achados que só o Nemotron registrou ficaram fora.

**Ponto de partida:**
- HEAD `29f5a4734dd9b9b1f54d2a34afae2dc82b7dbaf5` (master).
- `git status --short` inicial:
  - ` D docs/auditoria_backend_2026-09-25/RELATORIO.md` — outra sessão; preservado, não restaurado nem incluído em commit;
  - `?? .freebuff/`;
  - `?? "docs/auditoria_backend_2026-09-25/RELATORIO (space bunny).md"`;
  - `?? docs/auditoria_backend_2026-09-25/RELATORIO_CLAUDE_2026-09-29.md`.

**Ambiente:** todas as medições e testes rodaram só no TEST: Postgres 17 em Docker, `127.0.0.1:15432/gestor_pecas_test`, com round-trip de 1,26 ms em `SELECT 1`. **O REAL não foi acessado.**

---

## ONDA 1 — Chão de fábrica sob carga

### BK-05 · O harness de carga dava falsa confiança — **CORRIGIDO E PROVADO**

- **Antes:**
  - o harness autenticava só 24 dos 40 operadores, porque recursos de catálogo não são contas e o login os recusa com 403 por desenho;
  - não passava pelos gates reais (primeira peça, crachá, Setup);
  - quase nunca finalizava uma OP;
  - terminava "verde" mesmo nesses casos;
  - ignorava `PGPOOL_MAX_SIZE` e sempre usava pool 10.
- **Alteração** (`tests/load_test/run_operator_load_test.py`):
  - Os operadores vêm de `OPERATOR_PROFILES`.
  - O crachá é cadastrado para cada operador, e há um template de qualidade para setores com primeira peça estruturada.
  - A semente inclui o status `Set-Up` com `setup=TRUE` no catálogo. Sem ele, o Setup é recusado com `status_especial_indisponivel`.
  - O ciclo completo passa pelos gates reais:
    1. roteiro;
    2. Início;
    3. primeira peça, quando o setor exige: Setup → Início → checklist com medidas;
    4. Parada;
    5. Retomar;
    6. Finalizado com crachá.
  - Um `asyncio.Lock` por recurso canônico respeita a regra do produto de uma OP por recurso por vez. Os 40 perfis compartilham 32 recursos.
  - O harness **reprova com código 1** quando:
    - algum login de operador falha;
    - algum operador não finaliza;
    - há qualquer 5xx ou falha de transporte.
  - Novas opções `--pool-max` e `--report`.
- **Evidência:** todas as execuções da tabela da BK-01 abaixo tiveram 40/40 logins e 40/40 finalizações. Antes das correções da BK-01, a mesma versão do harness **REPROVOU** com mais de 100 respostas 503 e só 4/40 finalizações. Ou seja, o harness agora detecta a falha que antes escondia.
- **Testes:** o próprio harness, em 7 execuções com pool 4 e pool 10.

### BK-01 · Pool × threads, 503 intermitente, Início lento — **503 CORRIGIDO E PROVADO; meta de p95 < 1 s BLOQUEADA EXTERNAMENTE**

- **Antes** (harness corrigido, pool 4): mais de 100 respostas **503 `database_unavailable`** e só 4/40 finalizações.

- **Causa raiz 1: hold-and-wait.**
  - Transações de ação, como `_manter_intervalo_tx` e `_entrar_sem_demanda_tx`, seguravam uma conexão e pediam **outra** ao pool para ler calendário e intervalo (`_fora_do_turno`, `_intervalo_vigente`).
  - Com N ações simultâneas e pool N, todas seguravam uma conexão e esperavam a segunda até o `PGPOOL_TIMEOUT`, o que virava 503.

- **Causa raiz 2: PBKDF2 com conexão presa.**
  - `autenticar_usuario` calculava o hash (~0,5 s de CPU, 600 mil iterações) sem devolver a conexão.
  - Numa rajada de logins, isso esgotava o pool.
  - `criar_usuario` e `resetar_senha_usuario` tinham o mesmo padrão.

- **Alterações:**
  - `app/database/database.py`:
    - `Database.connection()` passa a ser reentrante via `ContextVar`. Dentro de `_na_conexao_da_transacao(cursor)`, as leituras aninhadas reutilizam a conexão da transação, e o commit e o rollback continuam com o dono da transação.
    - `_fora_do_turno` e `_intervalo_vigente` recebem `cursor=`.
    - O hash das senhas é calculado fora da conexão.
    - O rehash grava com `AND senha_hash = <hash verificado>`, para não sobrescrever uma troca de senha concorrente.
  - Bulkhead para leituras gerenciais:
    - `backend/api/dependencies/bulkhead.py`;
    - `CapacityLimiter` em `app.state.management_read_limiter`;
    - `GESTOR_WEB_MANAGEMENT_READ_CONCURRENCY`, padrão 2, faixa 1–32;
    - aplicado a `management`, `analytics` e `reports`, **só em GET**. Gravações da gestão seguem direto.
  - O número de conexões **não** foi aumentado.

- **Evidência** (40 operadores + 5 gestores, 30 s, `--thread-pool 100`):

  | Execução | 5xx | Logins | Finalizações | `acao_inicio` p95 | Outras ações p95 | `management_overview` p95 |
  |---|---|---|---|---|---|---|
  | Antes, pool 4 | >100 × 503 | 40/40 | 4/40 | — | — | — |
  | Depois, pool 4 | 0 | 40/40 | 40/40 | 2689–2906 ms | 1,9–2,5 s | 3,1–3,3 s |
  | Depois, pool 10 | 0 | 40/40 | 40/40 | **1721 ms** | finalizar 787, parada 949, retomar 815, setup 934 ms | 1872 ms |
  | Pool 4, sem gestores | 0 | 40/40 | 40/40 | 1787 ms | < 1 s | — |

  - Instrumentação de uma ação isolada: cerca de 30 consultas, 16,7 checkouts, ~136 ms de banco e ~315 ms segurando conexões.
  - Depois da correção, **0 checkouts aninhados** ("nested=0").
  - A mesma consulta leva 1,6–1,8 ms isolada e 4,6–10 ms dentro da ação: o custo está no processo Python, não no Postgres.
  - O Postgres usou no máximo ~0,68 núcleo durante a carga.
  - Linha do tempo:
    - os 40 logins terminam juntos, em ~4,7–5,1 s, porque o PBKDF2 é serializado no `auth_thread_limiter=8`;
    - os **40 Início disparam na mesma janela de ~0,9 s**, com 45 requisições em voo.
  - Com `sys.setswitchinterval(0.0005)`, as outras ações caíram ~30% (finalizar p95 de 2505 para 1714 ms), mas o **Início não mudou** (2689 para 2817 ms). A mudança **não foi aplicada**: foi uma execução única, com variância não medida.

- **Por que a meta de p95 < 1 s não fecha nesta arquitetura:**
  - Uma rajada de 40 Início simultâneos num **único processo Python**, que é a produção atual via NSSM, fica presa pelo GIL e pela ocupação do pool.
  - Com pool 4: 40 × ~315 ms ÷ 4 ≈ **3,1 s**. É o p95 medido.
  - Com pool 10: ≈ 1,3 s, mais a disputa de CPU. O medido foi 1,72 s.
  - Para ficar abaixo de 1 s com pool 4, cada Início teria de custar menos de ~100 ms de conexão e menos de ~25 ms de CPU. Isso é 3–4 vezes menos que hoje.
  - Os caminhos que fecham a meta estão fora do escopo da BK-01:
    - **(a)** mais de um processo uvicorn na VM, o que depende da BK-07 (lock de líder dos loops de background, Onda 2) e de uma decisão de infraestrutura;
    - **(b)** refatorar `operator_flow.executar` para reduzir as ~30 consultas e 16 checkouts por ação, mexendo no caminho crítico de regras MES;
    - **(c)** adotar um modelo de chegada realista, com operadores entrando no turno ao longo de minutos, em vez de uma rajada em 0,9 s. Isso muda o critério de aceite e é decisão do usuário.

- **Testes:**
  - `tests/test_operator_load_path.py` (**novo**, 3 testes):
    - a leitura aninhada reutiliza a conexão sem checkout;
    - fora do escopo, e em outra instância, a leitura volta ao pool;
    - o bulkhead limita GETs a 2 e deixa POST passar.
  - Regressão direcionada: **212 passed, 71 subtests passed**, em `test_resource_state_no_demand_and_break`, `test_stage4b_factory_shift`, `test_wave6a_calendario_operacional`, `test_user_management`, `test_database_professionalization` e `test_web_api`.

- **GATE W1:**

  | Item | Resultado |
  |---|---|
  | 40/40 logins | ✅ |
  | Finalização exercitada | ✅ 40/40 |
  | 0 respostas 5xx | ✅ |
  | Sem regressão no operador | ✅ |
  | Testes e harness verdes | ✅ |
  | `acao_inicio` p95 < 1 s com pool 4 e pool 10 | ❌ precisa de decisão de infraestrutura ou de critério. **Parado para decisão.** |
