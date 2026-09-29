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

- **Decisão do usuário (29/09/2026):** seguir para a Onda 2. A meta de p95 < 1 s fica **BLOQUEADA EXTERNAMENTE**, pois depende de decisão de infraestrutura (multiprocesso) ou de critério de carga. O 503 continua **CORRIGIDO E PROVADO**.

---

## ONDA 2 — Invariantes de concorrência

Todos os testes desta onda rodam só no TEST, cada um em schema próprio (`gestor_test_<uuid>`), criado e destruído pelo próprio teste.

### BK-02 · Lock do rateio sem identidade canônica — **CORRIGIDO E PROVADO**

- **Antes:**
  - `registrar_rateio_recurso` travava `hashtext(UPPER(recurso))` com o texto recebido.
  - `Laser Ensis 3015` e `LASER1` caíam em travas distintas, e cada uma gravava uma sessão física na mesma hora do mesmo recurso.
- **Alteração** (`app/database/database.py`):
  - Nova função única `_travar_recurso_tx(cursor, recurso)`. Ela resolve a identidade canônica (`resolve_resource_identity`), toma o `pg_advisory_xact_lock` e devolve o código canônico.
  - Todos os pontos que travavam recurso passam por ela.
  - O rateio grava e compara o recurso canônico. `listar_rateios_tempo_periodo` filtra pela identidade canônica.
- **Evidência / testes** (`tests/test_concurrency_invariants.py::test_rateio_por_alias_e_por_codigo_nao_se_sobrepoem`):
  - duas threads liberadas por barreira, uma com o alias e outra com o código, em horários sobrepostos;
  - resultado: 1 gravação e 1 `ValueError` "sobreposta"; o recurso salvo é `{LASER1}`;
  - **contraprova:** com o `database.py` do HEAD (via `git stash`), o teste falha com as duas sessões gravadas.

### BK-03 · TOCTOU no Início (enfileirar sem lock) — **CORRIGIDO E PROVADO**

- **Antes:**
  - A checagem de ocupação do fluxo (`recurso_em_uso`) roda antes e fora da transação do INSERT em `enfileirar_apontamento_operacional`, que não travava o recurso.
  - Dois Inícios simultâneos no mesmo recurso passavam a checagem.
  - Quem perdia na transição deixava a linha `Aguardando` recém-criada para trás.
- **Alteração:**
  - `app/database/database.py`:
    - `_conflito_recurso_exclusivo_tx` é a revalidação canônica: considera os 4 status que ocupam o recurso (`Em processo`, `Parada`, `Setup`, `Retrabalho`), pela máquina **ou** pelo evento de estado aberto.
    - `enfileirar_apontamento_operacional(..., recurso_exclusivo=False)` trava e revalida dentro da transação do INSERT quando o recurso é exclusivo. Em produção, o fluxo do operador sempre passa `recurso_exclusivo=True` (`backend/api/routers/operator.py:601`).
    - `transicionar_apontamento_operador` usa a mesma função.
    - Novo `descartar_inicio_nao_iniciado(id)`: apaga **somente** a linha `Aguardando` sem `data_inicio` e que não é retorno de retrabalho da Qualidade.
  - `mes/services/operator_flow.py`:
    - o conflito no INSERT devolve `operator_resource_occupied`;
    - o Início que perde na transição apaga apenas a linha que ele próprio acabou de criar.
- **Não aplicado, de propósito:** contar outras linhas `Aguardando` como ocupação. Fila legítima existe (finalização parcial, retorno de retrabalho, fila sem Início), e linhas órfãs travariam máquinas para sempre. `test_recurso_exclusivo_nao_permite_contornar_por_parada_e_retomada` continua verde e prova que a fila legítima sobrevive.
- **Evidência / testes:**
  - `test_dois_inicios_simultaneos_deixam_um_apontamento_e_um_conflito`: 5 rodadas com alias × código por barreira; sempre `["conflito", "iniciado"]` e exatamente 1 linha ativa (`Em processo`).
  - `test_revalidacao_no_insert_ve_o_recurso_ocupado_pelo_alias`.
  - `test_descarte_nao_apaga_fila_que_ja_produziu`.
  - `tests/test_operator_flow.py::test_inicio_que_perde_a_disputa_nao_deixa_fila_para_tras`. **Contraprova:** com o descarte neutralizado, o teste falha.
- **Fora do escopo, registrado:** a transição trava a linha (`FOR UPDATE`) antes do advisory lock, na ordem inversa do enfileirar. Não houve deadlock nas rodadas, porque o INSERT não trava linhas de outros apontamentos. Fica como observação.

### BK-07 · Loops de background sem líder — **CORRIGIDO E PROVADO**

- **Antes:**
  - Com mais de um processo web, cada processo subia o agendador de relatórios, o bot e o resumo do Telegram.
  - `send_report` faz check-then-act, e o mesmo relatório podia sair duas vezes.
  - Dois `getUpdates` concorrentes geram `409 Conflict`.
- **Alteração:**
  - Novo `app/database/leadership.py` com `LeaderLease`: `pg_try_advisory_lock` de sessão numa **conexão dedicada, fora do pool**.
    - Um lock por ciclo ocuparia 1 das 4 vagas do pool do operador o tempo todo no polling do Telegram.
    - A cada ciclo, o líder confirma a sessão com `SELECT 1` e quem não é líder tenta assumir.
    - Se o líder morrer, o PostgreSQL solta o lock com a conexão.
    - Sem PostgreSQL (fakes, prévia local), fica no-op e devolve `True`, pois há um único processo.
  - `backend/api/main.py`:
    - `_report_scheduler_loop`, `_telegram_bot_loop` e `_telegram_digest_loop` só executam o ciclo quando `_leader_cycle` confirma a liderança, com locks 874_210_308/309/310, na faixa do lock do catálogo (874_210_307);
    - o lease é liberado no `finally` do cancelamento;
    - o bot que não é líder zera o offset em memória e relê o cursor persistido ao assumir.
  - A operação com processo único não muda: o primeiro ciclo já pega o lock.
- **Não alterados, pois a auditoria os confirmou mitigados:** shift_boundary (`FOR UPDATE`), outbox TOTVS (`SKIP LOCKED` + lease, ver BK-12) e catálogo (advisory lock).
- **Evidência / testes** (`test_um_so_lider_e_a_morte_dele_libera_a_vez`, com PostgreSQL real):
  - dois leases disputam por barreira e exatamente 1 vira líder;
  - o líder reconfirma e o reserva segue recusado;
  - com `pg_terminate_backend` na sessão do líder (processo morto), o reserva assume e o antigo líder passa a ser recusado.
  - A prova é no nível do lock, que é o único ponto de decisão dos 3 laços. O teste com dois `TestClient` sugerido pela auditoria não foi montado, porque exigiria Telegram e relógio reais nos laços.
  - Regressão: `test_report_automation_messaging`, `test_telegram_bot` e `test_telegram_alerts` (54 passed) e `test_web_api` (59 passed).

### BK-12 · Lease da outbox menor que o pior lote — **CORRIGIDO E PROVADO**

- **Antes:**
  - O lote inteiro (até 10) recebia um único lease de 120 s, mas cada POST pode levar o timeout inteiro (30 s).
  - Os últimos itens venciam ainda na fila do worker. Outro worker os recuperava (`recuperar_envios_abandonados_totvs`) e os enviava de novo, e o primeiro worker também os enviava.
- **Alteração:**
  - `app/database/totvs_outbox_repository.py`: novo `renovar_reserva_outbound_totvs(ids, worker, lease_seconds)`. Ele estende o lease só dos itens ainda `SENDING` deste worker e não vencidos, e devolve os ids ainda reservados.
  - `mes/services/totvs_outbox_worker.py`:
    - antes de cada envio, faz o heartbeat do restante do lote; o item que já não é do worker é pulado, sem envio;
    - o lease efetivo nunca fica abaixo de 2 × o timeout do gateway.
  - Preservados:
    - at-least-once: o item recuperado volta a `RETRY` com a mesma `idempotency_key`;
    - `idempotency_key`;
    - ordem causal por OP (F19): a reserva não mudou;
    - a cadência de um lote por ciclo.
- **Evidência / testes** (`tests/test_totvs_outbox.py::test_lote_lento_nao_envia_o_mesmo_item_duas_vezes`):
  - 3 itens de OPs distintas; POST de 70 s em relógio controlado;
  - o worker B roda no meio do lote do worker A e depois de 1 h;
  - resultado: cada chave enviada **uma** vez e tudo `SENT`;
  - **contraprova:** sem o heartbeat, o resultado é `['lote-0', 'lote-1', 'lote-1', 'lote-2', 'lote-2']`.
  - F19 (`test_reinicio_processa_pending_antigo_sem_perder_mensagem`) e `test_totvs_outbox_notifications` verdes.

### GATE W2

| Item | Resultado |
|---|---|
| Alias × código com zero sobreposição | ✅ `test_rateio_por_alias_e_por_codigo_nao_se_sobrepoem` |
| 2 threads → 1 sucesso + 1 conflito | ✅ 5/5 rodadas |
| Teste com 2 processos | ✅ 2 sessões PostgreSQL de líder, e a morte de uma libera a vez |
| 1 envio lógico por `idempotency_key` | ✅ `test_lote_lento_nao_envia_o_mesmo_item_duas_vezes` |
| F19 segue válido | ✅ |
| Regressão direcionada | ✅ 217 passed, 6 subtests (operador, concorrência, outbox, profissionalização, estado de recurso, primeira peça, regras MES, load path) + 54 (relatórios/Telegram) + 59 (`test_web_api`) |

---

## ONDA 3 — Segurança de fronteira

Commit `fix: harden backend trust boundaries`. O REAL não foi acessado. O SigmaNEST de produção também não foi consultado: os testes usam conexão falsa e um parser de referência da gramática ODBC.

### BK-04 · CSV/XLSX com injeção de fórmula — **CORRIGIDO E PROVADO**

- **Antes:**
  - `export_csv` (`backend/api/routers/reports.py`) gravava o texto de origem cru.
  - `safe_text` (`backend/api/report_workbook/kit.py`) só neutralizava `= + - @`. TAB e CR também abrem fórmula no Excel e no LibreOffice (OWASP CSV Injection).
- **Alteração:**
  - `safe_text` passa a cobrir também `\t` e `\r`.
  - O CSV usa o mesmo `safe_text` via `_csv_cell`: há uma só regra para XLSX e CSV. Número continua número (`-5` não vira texto), e dict/list viram JSON.
- **Evidência / testes:**
  - `test_web_api::test_relatorio_csv_neutraliza_formula_de_texto_livre`: `=HYPERLINK(...)`, `\tcmd` e `\r@SUM(1)` saem com o prefixo `'`; `-5` e `Normal` saem intactos.
  - **Contraprova:** sem a correção, o teste falha.

### BK-10 · Sem teto de corpo — **CORRIGIDO E PROVADO**

- **Antes:** nenhum middleware limitava o corpo. Um POST de 10 MB no login público era lido inteiro e parseado.
- **Alteração:**
  - `backend/api/body_limit.py`: `BodySizeLimitMiddleware`, ASGI puro, com teto padrão de 1 MiB:
    - recusa pelo `Content-Length` sem ler o corpo;
    - no corpo chunked, conta os bytes reais e interrompe no estouro com `PayloadTooLarge`, um `HTTPException` que o FastAPI repassa sem virar 400.
  - Exceções explícitas:
    - `/api/v1/quality/drawings`: teto próprio de 20 MB de PDF em base64;
    - `/PcfIntegService`: o SOAP já tem limite e responde com fault SOAP.
  - Registrado como middleware mais interno. Por isso o 413 sai com `X-Request-ID` e os headers de segurança.
  - `backend/api/errors/__init__.py`: um handler dedicado devolve o payload padrão (`code=payload_too_large`).
- **Evidência / testes:**
  - `test_corpo_gigante_recebe_413_sem_chegar_ao_handler`:
    - 10 MB com `Content-Length` → 413;
    - 20 × 128 KB chunked → 413;
    - `autenticar_usuario` nunca é chamado.
  - `test_teto_de_corpo_respeita_upload_de_desenho_e_soap`: 2 MB de desenho e 2 MB de SOAP não recebem o 413 genérico.
  - **Contraprova:** sem o middleware, a resposta é 422 ou 401, e o handler roda.

### BK-18 · `capabilities` expunha configuração sem sessão — **CORRIGIDO E PROVADO**

- **Antes:** `GET /api/v1/system/capabilities` devolvia regras, integrações e flags a qualquer anônimo, inclusive pelo túnel público.
- **Alteração:**
  - `backend/api/routers/system.py`: sem sessão válida, a resposta é só `{"simulation": ...}`, o único campo que o `ReferenceClockProvider` do front lê antes do login.
  - Um cookie forjado ou expirado conta como anônimo.
  - O bloco `simulation` passou a vir de um helper único, sem duplicação.
- **Evidência / testes:**
  - `test_capabilities_anonimo_recebe_so_o_relogio`: as chaves são `{"simulation"}`, também com o cookie `gestor_session` forjado.
  - O teste antigo do payload completo agora faz login antes.

### BK-21 · Comandos aceitavam campo desconhecido — **CORRIGIDO E PROVADO**

- **Antes:** os comandos de escrita em `backend/api/schemas/common.py` e `quality.py` ignoravam campo extra em silêncio. Um cliente podia mandar `usuario_id` e acreditar que ele fosse aplicado.
- **Alteração:**
  - `model_config = ConfigDict(extra="forbid")` nos 18 comandos: 9 em `common` e 9 em `quality`. `ErrorResponse` e `PageMeta` são de leitura e ficaram de fora.
  - O strip de strings não mudou: `str_strip_whitespace` não foi adicionado, para não alterar comportamento.
  - **Consumidor corrigido na origem:**
    - `web/src/pages/home/PausesPage.tsx` e `ShiftsPage.tsx` reenviavam a linha lida inteira, com `atualizado_por` e `atualizado_em`, no Ativar/Desativar. Com `forbid`, isso daria 422.
    - As duas telas passam a enviar só os campos do comando.
    - Os demais POSTs do front já montavam o payload campo a campo (conferidos: chamadas, crachás, usuários, qualidade, bancada).
- **Evidência / testes:**
  - `test_comando_com_campo_desconhecido_recebe_422`: `{"op":..., "usuario_id": 1}` → 422 `extra_forbidden`, e nada é aberto.
  - `test_todo_comando_de_escrita_recusa_campo_extra`: 18 subtestes, um por schema. Um comando novo sem `forbid` quebra o teste.
  - `web/src/test/pauses.test.tsx`: a fixture ganhou os campos de auditoria, e o corpo do POST tem exatamente as 7 chaves do comando.
  - **Contraprova:**
    - sem o `forbid`: 19 falhas;
    - sem a correção da tela: o vitest falha.
  - `tsc --noEmit` verde; `pauses` e `shifts`: 18/18.

### BK-15 · SigmaNEST: senha sem escape, TLS confiando em qualquer certificado, timeout que falhava aberto — **escape e timeout CORRIGIDOS E PROVADOS; validação TLS com mecanismo pronto e ativação BLOQUEADA EXTERNAMENTE**

- **Antes** (`backend/integrations/sigmanest_sqlserver.py`):
  - `PWD={senha}` era concatenado cru. Um `;` na senha encerrava o valor e o resto virava outra chave do DSN.
  - O `mask_dsn` mascarava só até o primeiro `;`.
  - `TrustServerCertificate=yes` era fixo.
  - Se `conexao.timeout` falhasse, havia só um `LOGGER.warning`, e a consulta seguia sem limite.
- **Alteração:**
  - `UID` e `PWD` vão entre chaves, com `}` dobrado (gramática ODBC). O `mask_dsn` reconhece o valor entre chaves.
  - `Encrypt=yes` passa a ser explícito. `SIGMANEST_TRUST_SERVER_CERTIFICATE=no` liga a validação do certificado pela CA do Windows. `SIGMANEST_HOSTNAME_IN_CERTIFICATE` é opcional, porque o `SERVER` é um IP.
  - `SIGMANEST_QUERY_TIMEOUT` inválido ou ≤ 0 recusa o gateway já na construção.
  - Se a atribuição do timeout falhar, a conexão é fechada e `SigmaNestConfigurationError` é levantado. O sync aborta sem consultar.
  - O timeout agora vale também para a conexão injetada.
  - Documentado no `.env.example`.
- **Por que a validação TLS não virou padrão:**
  - O sync está ativo no `.env` deste ambiente; conferi só a presença das chaves, sem valores.
  - O certificado do SQL Server do SigmaNEST (`192.168.0.218`) não foi comprovado como emitido por uma CA interna. Um SQL Server sem certificado provisionado usa um certificado autoassinado.
  - Ligar a validação por padrão derrubaria o sync em produção sem a CA instalada.
  - **Para ativar:** a TI instala a CA interna no Windows do servidor do Gestor e define `SIGMANEST_TRUST_SERVER_CERTIFICATE=no`. Isso depende de infraestrutura externa.
- **Evidência / testes** (`tests/test_sigmanest_planning.py`):
  - `test_senha_com_separadores_chega_inteira_ao_driver`: a senha `a;b=c}d{e` e o usuário `ti;consulta` chegam íntegros pelo parser ODBC de referência, e nenhum trecho aparece no DSN mascarado.
  - `test_certificado_validado_quando_a_ca_interna_for_configurada`: sem a variável, o DSN mantém `TrustServerCertificate=yes`; com `=no`, sai `TrustServerCertificate=no` e `HostNameInCertificate`.
  - `test_timeout_aplicado_em_toda_conexao`, `test_timeout_nao_aplicado_aborta_o_sync_sem_consultar` (nenhum `execute`; conexão fechada) e `test_timeout_invalido_recusa_o_gateway`.
  - **Contraprova:** sem a correção, os 5 testes novos falham.
  - Os 37 testes existentes, com 808 subtestes, seguem verdes.

### BK-09 · Mesmo role de banco para TEST e REAL — **BLOQUEADO EXTERNAMENTE**

- **Motivo:** a correção é `REVOKE CONNECT ON DATABASE gestor_pecas FROM <role de TEST>` mais a troca da credencial de `DATABASE_URL` ou `TEST_DATABASE_URL`.
  - Isso altera a ACL do banco REAL.
  - Isso cria roles na instância que hospeda o REAL.
  - Isso troca segredos no `.env`.
  - Os três casos são critério de parada ("REAL necessário" / "segredo necessário"). Nada foi executado, e o REAL não foi consultado.
- **Runbook para a janela aprovada** (rodar como superusuário, fora do app):

  ```sql
  CREATE ROLE gestor_test LOGIN PASSWORD '<nova-senha>';
  ALTER DATABASE gestor_pecas_test OWNER TO gestor_test;   -- e REASSIGN OWNED no banco de teste
  REVOKE CONNECT ON DATABASE gestor_pecas FROM PUBLIC, gestor_test;
  REVOKE CONNECT ON DATABASE gestor_pecas_test FROM PUBLIC, gestor_app;
  GRANT CONNECT ON DATABASE gestor_pecas TO gestor_app;
  ```

  Depois, atualize `TEST_DATABASE_URL` com `gestor_test`.
- **Teste de aceite:** a DSN de TEST apontada para `gestor_pecas` deve receber `permission denied for database`.

### GATE W3

| Item | Resultado |
|---|---|
| bandit `-r backend mes app -ll` (M/H) | ✅ 0 Medium, 0 High |
| pip-audit `-r requirements.txt -r requirements-dev.txt` | ✅ No known vulnerabilities found |
| Auth / CSRF / SOAP F4 / relatórios / qualidade / SigmaNEST | ✅ 388 passed, 993 subtests: `test_web_api`, `test_totvs_integration`, `test_ai`, `test_dev_observatory`, `test_database_professionalization`, `test_intelligence_reports`, `test_report_automation_messaging`, `test_stage4b_factory_shift`, `test_quality_inspection`, `test_wave6b_gate_setup_qualidade`, `test_sigmanest_planning`, `test_sigmanest_gateway` |
| Front | ✅ `tsc --noEmit`; vitest `pauses` + `shifts` 18/18 |
| REAL acessado | ❌ Não |
