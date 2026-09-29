# Auditoria total do backend — Gestor de Peças / MES (Claude, 29/09/2026)

> **Somente diagnóstico.** Nenhum arquivo de código, teste, schema ou configuração foi alterado.
> O banco REAL não foi tocado. Todas as operações destrutivas rodaram em **schemas descartáveis no TEST**, que foram removidos ao final.

## 0. Contexto e limites

| Item | Valor |
|---|---|
| HEAD | `29f5a4734dd9b9b1f54d2a34afae2dc82b7dbaf5` (master) |
| `git status` inicial | `?? .freebuff/` · `?? "docs/auditoria_backend_2026-09-25/RELATORIO (space bunny).md"` |
| Banco | PostgreSQL 17 · `127.0.0.1:15432` · somente `gestor_pecas_test` (62 tabelas em `public`, 51 migrations aplicadas) |
| Documentos lidos | `AGENTS.md`, `ROADMAP.md`, `STATUS_ATUAL.md` |
| Outras sessões | Esta pasta já tinha `RELATORIO.md` (25/09) e `RELATORIO (space bunny).md`. **Nenhum dos dois foi sobrescrito.** Este é um terceiro arquivo. Os achados convergentes estão cruzados na §4. |
| Invariantes F1–F21 | Tratados como fechados. **Nenhum foi reaberto.** F4 (SOAP fail-closed) e F19 (ordem causal do outbox) foram reverificados e continuam valendo. |

### 0.1 Como a evidência foi obtida

- **Código:** leitura dirigida com `arquivo:linha` e varredura AST para medir o tamanho das funções e listar as rotas sem auth ou CSRF.
- **Catálogo:** consultas somente-leitura em `pg_constraint`, `pg_indexes` e `information_schema` no TEST.
- **EXPLAIN (ANALYZE, BUFFERS):**
  - rodou no schema descartável `audit_explain_*` com 300 mil apontamentos e 600 mil eventos;
  - o schema foi removido no `finally`;
  - as saídas ficaram no scratchpad da sessão (`explain.txt`).
- **Suíte:** `python -m pytest tests -q -p no:cacheprovider --ignore=tests/test_e2e_smoke.py -o addopts="" -rfE`.
  - Resultado: **1324 passaram, 1 falhou, 1 skip, 2071 subtests** em 608 s.
- **Teste de carga:** `python -m tests.load_test.run_operator_load_test --operators 40 --seconds 45`, rodado 2 vezes.
  - Cada execução usou um schema isolado `gestor_loadtest_*`, removido pelo próprio harness.
  - O arquivo versionado `tests/load_test/last_run_report.json` foi **restaurado com `git checkout`** depois de cada execução.
- **Segurança estática:**
  - `bandit -r backend mes app -ll` → **0 achados de severidade média ou alta**.
  - `pip-audit -r requirements.txt` → **nenhuma vulnerabilidade conhecida**.

---

## 1. Matriz do sistema

| Dimensão | Inventário | Evidência |
|---|---|---|
| Módulos | `backend/` 67 arq / 13,5 mil linhas · `mes/` 93 / 27,5 mil · `app/` 31 / 15,2 mil | `find … \| wc` |
| Endpoints | 123 rotas FastAPI em 19 routers + SOAP `/PcfIntegService`. As rotas públicas por desenho são: login, `/health`, `/capabilities`, login/logout/página do dev_observatory e SOAP (este com uma guarda própria). | Varredura AST |
| Tabelas | 62, todas com PK. Constraints: 56 FK, 102 CHECK, 22 UNIQUE. **21 FKs não têm índice de suporte.** | `pg_constraint` |
| Migrations | 51 em `schema_migrations`, aplicadas no startup por `apply_migrations` (`app/database/database.py:234-236`) | Consulta ao TEST |
| Workers (loops em processo) | 7: report_scheduler, totvs_outbox, telegram_bot, telegram_digest, sigmanest_sync, shift_boundary, dev_observatory (`backend/api/main.py:158-400`, criados em `:473-520`) | Código |
| Integrações | TOTVS WSPCP (outbound, via outbox) · TOTVS SOAP (inbound) · SigmaNEST SQL Server (somente leitura) · Telegram (bot e digest) · Groq (IA) | Código |
| Testes | 73 arquivos `tests/test_*.py`, 1325 testes (1324 verdes) e um harness de carga | pytest |
| CI/CD | `ci.yml`, `e2e.yml`, `deploy.yml` (runner self-hosted na VM Windows, com health gate) | `.github/workflows` |

---

## 2. Scores (0–10)

| Área | Nota | Justificativa curta |
|---|---|---|
| Arquitetura / Lógica MES | **7,5** | Os pontos fortes são a máquina de estados com `FOR UPDATE`, o relógio do servidor como autoridade, o OEE sem corte silencioso e o outbox transacional. Pesam contra as god-functions e o acoplamento `facade→app.database.schema`. |
| Segurança | **8,0** | A autenticação é forte: `session_version`, CSRF com `compare_digest`, PBKDF2 600k, throttle persistente e SOAP fail-closed. Bandit e pip-audit saíram limpos. Os problemas pendentes são CSV injection, a falta de limite de body e um único role de banco para TEST e REAL. |
| Dados / Concorrência | **7,5** | O banco garante um único estado aberto por recurso (índice único), o outbox usa `SKIP LOCKED` e ordem causal, e o double-submit é seguro. Contra: chave de lock divergente no rateio, TOCTOU no enfileiramento, `CHECK NOT VALID` e FKs sem índice. |
| Performance | **6,0** | O Início leva p50 de 2 s. Houve um 503 por esgotamento do pool. A sobreposição de período cai em Seq Scan (377 ms com 600 mil eventos). O login leva 5–6 s sob rajada. |
| Resiliência / Operação | **6,0** | A favor: `/health` devolve 503 quando o banco falha, há health gate no deploy e backoff no outbox. Contra: loops sem eleição de líder, deploy sem rollback automático, logs sem correlação e fuso horário herdado do SO do host. |
| Testabilidade / Manutenção | **6,5** | A suíte é ampla e está verde (99,9%). Porém o harness de carga derivou e dá falsa confiança, um teste de migração não é hermético e 18 funções passam de 200 linhas. |

---

## 3. Achados (P0 → P3)

**Contagem:** P0 **0** · P1 **3** · P2 **7** · P3 **16**

Nenhum P0 foi encontrado: não há perda silenciosa de dado industrial, bypass de autenticação nem escrita no REAL.

Legenda de status:
- **CONFIRMADO** — reproduzido por execução ou benchmark.
- **CONFIRMADO-INSP** — comprovado por inspeção do código ou do schema.
- **LATENTE** — o defeito existe, mas só se manifesta sob uma condição de deploy que não foi verificada.

---

### BK-01 · P1 · CONFIRMADO — Pool de conexões muito menor que o pool de threads: 503 intermitente e Início com p50 de 2 s

- **Área:** B (Dados/Performance)
- **Arquivo:linha:**
  - pool: `app/database/connection.py:22-23` (`max_size`, `timeout`), `app/database/config.py:157`;
  - threads: `backend/api/main.py:469-470` (`total_tokens = sync_thread_pool_size`).
- **Fluxo:** o operador aperta Início, Parada ou Finalizar. O handler síncrono roda numa das 100 threads e disputa um pool de 10 conexões com `timeout=5s`. Ao mesmo tempo, os dashboards gerenciais e os 7 loops de background usam o mesmo pool.
- **Evidência** (40 operadores + 5 gestores, 45 s, pool 10):

  | Endpoint | Execução 1 (p50 / p95 / p99) | Execução 2 (p50 / p95) |
  |---|---|---|
  | `acao_inicio` | 2021 / 2555 / 2686 ms | 2002 / 2504 ms |
  | `acao_parada` | 518 / 1538 ms | 1167 / 1596 ms |
  | `management_overview` | p99 1850 ms | — |
  | `login` | p50 4884 ms (PBKDF2 serializado no `auth_thread_limiter`) | p50 6203 ms |

  - Execução 1: **1× HTTP 503 `database_unavailable` em `acao_parada`**, ou seja, o operador ficou sem resposta útil.
  - Execução 2: nenhum 5xx. O 503 é **intermitente**.
- **Agravante:** o harness só autenticou **24 dos 40 operadores** (ver BK-05). A carga real de um turno cheio é **maior** que a medida.
- **Agravante 2:** o `.env` local define `PGPOOL_MAX_SIZE=4`, mas o harness ignora essa variável e sempre usa 10. Com 4 conexões, o cenário é pior e **não foi medido**.
- **Impacto:** o operador vê o botão demorar 2–3 s ou receber um erro, no chão de fábrica e em horário de pico (início de turno). O retry é seguro graças à máquina de estados, mas gera fricção e desconfiança.
- **Causa:** 100 threads concorrem por 10 conexões, sem uma fila justa por prioridade. As telas gerenciais pesadas e as ações do operador competem pelo mesmo recurso.
- **Padrão:** recurso escasso compartilhado entre um caminho crítico e caminhos de leitura pesada (falta de *bulkhead*).
- **Recomendação:**
  1. dimensionar `sync_thread_pool_size` próximo de `PGPOOL_MAX_SIZE` para que a fila fique no anyio e não no pool com timeout;
  2. separar um pool, ou um limiter, para leitura gerencial;
  3. confirmar o `PGPOOL_MAX_SIZE` da VM de produção;
  4. fazer o harness respeitar `PGPOOL_MAX_SIZE`.
- **Teste para a correção:** rodar o harness com 40 operadores efetivos, com pool 4 e com pool 10. Critério: 0 respostas 5xx e p95 de `acao_inicio` abaixo de 1 s.
- **Convergência:** coincide com o `P0-01` do `RELATORIO.md` (25/09). Classifiquei como P1 porque o retry é idempotente e a taxa observada foi de 1 em cerca de 190 ações.

### BK-02 · P1 · CONFIRMADO-INSP — A chave do advisory lock no rateio não passa por `resolve_resource_identity`

- **Área:** A/B
- **Arquivo:linha:** `app/database/database.py:4922-4925` (`registrar_rateio_recurso` usa `str(recurso).strip()` cru). Os outros 5 call sites (`:4009`, `:4049`, `:4093`, `:4259`, `:4292`) usam a identidade canônica.
- **Fluxo:** um alias como "Laser Ensis 3015" e o código canônico "LASER1" geram `hashtext` diferentes. São travas distintas, então não há exclusão mútua entre o rateio e a transição de estado.
- **Evidência:** reconfirmado no HEAD `29f5a47`. O achado é idêntico ao `P1-04` do `RELATORIO.md`, que já descreve a prova com mais detalhe.
- **Impacto:** abre caminho para sessões físicas sobrepostas do mesmo recurso em `sessoes_recurso`, que alimenta o OEE.
- **Causa:** a resolução de identidade foi aplicada em 5 call sites e esquecida no 6º.
- **Padrão:** derivação de chave replicada em vez de extraída para um ponto único.
- **Recomendação:** criar um helper único `_chave_lock_recurso()` e gravar a identidade canônica em `sessoes_recurso`.
- **Teste para a correção:** dois concorrentes, um com o alias e outro com o código canônico. O segundo deve receber o erro de sobreposição.

### BK-03 · P1 · CONFIRMADO-INSP — `enfileirar_apontamento_operacional` não toma o advisory lock do recurso (TOCTOU)

- **Área:** A/B
- **Arquivo:linha:**
  - `app/database/database.py:2084` (a função não contém nenhum `pg_advisory_xact_lock` — contagem 0);
  - a checagem `recurso_em_uso` em `mes/services/operator_flow.py` roda numa transação separada e antes do INSERT.
- **Fluxo:** dois Inícios simultâneos, de OPs diferentes, na mesma máquina. As duas leituras não encontram nada, os dois INSERTs são feitos e ficam 2 linhas `Aguardando` para a mesma máquina.
- **Evidência:** inspeção no HEAD atual. Converge com o `P1-05` do `RELATORIO.md`.
- **Mitigação existente:** a transição seguinte (`transicionar_apontamento_operador`) toma o advisory lock e o `FOR UPDATE`, e barra a exclusividade real. **O dado físico não é corrompido.** O que fica errado é a fila de apontamentos e o Andon.
- **Impacto:** fila e Andon mostram dois apontamentos ativos na mesma máquina.
- **Causa e padrão:** check-then-act sem lock, num caminho de escrita que é irmão dos que usam lock.
- **Recomendação:** tomar o mesmo advisory lock canônico dentro da transação do INSERT e repetir a checagem dentro dela.
- **Teste para a correção:** duas threads enfileirando na mesma máquina ao mesmo tempo. Deve resultar em exatamente 1 linha ativa e 1 conflito 409.

### BK-04 · P2 · CONFIRMADO — CSV de relatório sem neutralização de fórmula (CSV injection)

- **Área:** C (OWASP A03 Injection / ASVS V5)
- **Arquivo:linha:**
  - `backend/api/routers/reports.py:218-240` (`csv.DictWriter` escreve os valores crus);
  - para comparação, o XLSX usa `safe_text` (`backend/api/report_workbook/kit.py:107-111`, aplicado em `:155`).
- **Fluxo:** um texto livre digitado por um operador (observação, motivo) que comece com `=`, `+`, `-` ou `@` vai para o CSV. Quando o gestor abre o arquivo no Excel, o conteúdo é interpretado como fórmula.
- **Evidência:** inspeção. O caminho XLSX neutraliza esses caracteres, e o caminho CSV não.
- **Impacto:** execução de fórmula ou exfiltração via `HYPERLINK` na máquina do gestor. Requer um perfil gerencial para exportar.
- **Causa:** a sanitização foi implementada por formato, não na fronteira de saída.
- **Recomendação:** aplicar `safe_text` também no CSV e incluir TAB (`\t`) e CR (`\r`) no conjunto de prefixos (P3 no XLSX).
- **Teste para a correção:** valor `=HYPERLINK("x")` → a célula do CSV deve começar com `'`.

### BK-05 · P2 · CONFIRMADO — O harness de carga derivou do produto e dá falsa confiança

- **Área:** F
- **Arquivo:linha:** `tests/load_test/run_operator_load_test.py:128-142` itera `OPERATOR_SECTORS`, e não `OPERATOR_PROFILES` (`app/core/operator_sectors.py:155-161` e `:263-266`).
- **Evidência:**
  - **16 de 40 logins retornam 403 `user_role_invalid`.** Os níveis `setor_solda_aco`, `setor_solda_aluminio`, `setor_solda_robo`, `setor_prototipo` e `setor_proj_ferramentaria` são entradas de catálogo, e não contas, conforme o comentário em `operator_sectors.py:155-160`. `normalize_user_level` os rejeita (`app/core/permissions.py:126-130`) **por desenho**.
  - **`acao_finalizar`: 0 de 24 OK.** O harness não cumpre os gates da Wave 5: `primeira_peca_gate_obrigatorio` 11×, `cracha_obrigatorio` 5×, `transicao_invalida` 7–8×.
  - O `last_run_report.json` versionado (14/09) mostra 3614 requisições; a execução de hoje fez cerca de 2200.
- **Impacto:** a Solda (5 setores) e o fechamento de apontamento **não passam por teste de carga**. O relatório do harness ainda afirma que nenhuma ação travou, o que passa uma segurança indevida.
- **Causa:** o harness não acompanhou o split da Solda (migration 28/29) nem os gates da Wave 5.
- **Padrão:** teste de sistema sem asserção de cobertura, que degrada em silêncio.
- **Recomendação:**
  1. usar `OPERATOR_PROFILES`;
  2. cumprir o gate de primeira peça e o crachá no roteiro do operador simulado;
  3. **fazer o harness falhar** quando houver algum 403 de login ou 0 finalizações OK.
- **Teste para a correção:** o próprio harness, com a asserção de 40/40 logins e ao menos 1 finalização por operador.

### BK-06 · P2 · CONFIRMADO — Sobreposição de período vira Seq Scan que cresce com o histórico

- **Área:** B
- **Arquivo:linha:**
  - `app/database/database.py:4594-4599` (eventos, com `UPPER(COALESCE(e.tipo_setor,''))`, que anula o índice `(tipo_setor, data_inicio)`);
  - `:5010-5011` (`sessoes_recurso`);
  - `:3756-3757`, `:3833` e `:4931` (apontamentos).
- **Evidência:** `EXPLAIN (ANALYZE, BUFFERS)` com 600 mil eventos. O predicado `data_inicio < fim AND COALESCE(data_fim, fim) > inicio` resultou em **Seq Scan, 377 ms, 598.559 linhas descartadas, buffers hit=5109 read=2299**. O filtro de apontamentos por setor e dia deu Parallel Seq Scan de 93,7 ms.
- **Refutado no mesmo benchmark:** a consulta de recurso ocupado leva **1,19 ms** e usa os índices parciais. Está saudável.
- **Impacto:** o custo das telas de OEE, timeline e relatórios cresce linearmente com o histórico. O volume do REAL **não foi medido**.
- **Causa:** não há limite inferior indexável (por exemplo `data_inicio >= inicio - janela_max`), não há índice GiST ou `tsrange`, e o `UPPER` é aplicado na coluna indexada.
- **Recomendação:**
  - adicionar um limite inferior sargável;
  - usar índice de expressão coerente com o predicado ou normalizar `tipo_setor` na escrita;
  - avaliar um índice GiST sobre `tsrange(data_inicio, COALESCE(data_fim,'infinity'))`.
- **Teste para a correção:** o mesmo seed deve mostrar Index/Bitmap Scan e menos de 20 ms.
- **Convergência:** `P1-01` e `P1-06` do `RELATORIO.md`.

### BK-07 · P2 · LATENTE — Os 7 loops de background rodam em todo processo web, sem eleição de líder

- **Área:** E/D
- **Arquivo:linha:** `backend/api/main.py:473-520`
- **Evidência de cada efeito com 2 ou mais processos:**
  - **Telegram bot** (`main.py:225-259`): o cursor é persistido (`obter_cursor_telegram_bot`/`avancar_cursor_telegram_bot`, `database.py:169`). Isso **refuta** a suspeita anterior de offset só em memória. Porém dois `getUpdates` concorrentes geram `409 Conflict` na API do Telegram e podem duplicar respostas.
  - **Envio de relatório agendado** (`mes/services/report_messaging.py:47-90`): check-then-act. `obter_entrega_relatorio_por_idempotencia` é chamado antes do envio, sem lock. Dois processos podem **enviar o mesmo relatório duas vezes** ao Telegram. A geração em si é idempotente por `ON CONFLICT` (`report_repository.py:67`).
  - **shift_boundary:** mitigado pela máquina de estados com `FOR UPDATE`. Uma segunda aplicação vira no-op.
  - **Outbox TOTVS:** mitigado por `SKIP LOCKED` e lease (ver BK-12).
  - **catálogo:** protegido por `pg_try_advisory_lock` (`database.py:246`). Positivo.
- **Status LATENTE:** o deploy atual é um único serviço Windows (`Restart-Service gestor-pecas`, `deploy.yml`). A quantidade de workers do uvicorn na VM **não foi verificada**.
- **Recomendação:** usar um lock de líder (`pg_try_advisory_lock` por loop, como o catálogo já faz), ou impor e documentar a regra de 1 worker.
- **Teste para a correção:** dois `TestClient` com lifespan contra o mesmo schema. Deve haver exatamente um `send_report` por chave de idempotência.

### BK-08 · P2 · CONFIRMADO-INSP — Deploy sem rollback automático e dependências sem pin exato

- **Área:** E/C (supply chain)
- **Arquivo:linha:**
  - `.github/workflows/deploy.yml:75` (`robocopy /MIR`), `:81` (`pip install -r requirements.txt`), `:90` (`Restart-Service`), `:92-105` (health gate de 60 s que só faz `throw`);
  - `requirements.txt:1-4` (`openpyxl`, `psycopg[binary]`, `psycopg_pool` e `python-dotenv` sem versão; os demais usam faixas; nenhum tem hash);
  - migrations no startup: `app/database/database.py:234-236`.
- **Impacto:** se o health gate falhar, a VM fica com o código novo quebrado e as migrations já aplicadas. Não existe um passo que volte à versão anterior. Um `pip install` pode trazer uma versão maior nova de `psycopg` sem revisão.
- **Positivo:** o health gate existe, o `.env`, `dados/` e `backups/` são preservados (`/XF .env /XD dados dev_reports backups`) e o pip-audit está limpo hoje.
- **Recomendação:**
  - gerar um lockfile com hashes (`pip-compile --generate-hashes`);
  - fazer snapshot do diretório e da venv antes do `/MIR` e restaurá-lo no `throw`;
  - fazer backup do banco antes das migrations de schema.
- **Teste para a correção:** um deploy de teste com uma rota `/health` forçada a 503. A versão anterior deve voltar a responder.

### BK-09 · P2 · CONFIRMADO-INSP — O mesmo role de banco (`gestor_app`) atende TEST e REAL na mesma instância

- **Área:** C (menor privilégio)
- **Evidência:** `DATABASE_URL` e `TEST_DATABASE_URL` usam o mesmo usuário. Isso foi verificado comparando só o usuário das DSNs, **sem imprimir as senhas**. O guard contra REAL na aplicação é forte (positivo), mas é a única barreira.
- **Impacto:** um bug, ou um script de teste mal apontado, com a credencial de TEST consegue escrever no REAL. O banco não oferece segunda linha de defesa.
- **Recomendação:** criar roles separados (`gestor_test`, `gestor_app`) com `REVOKE CONNECT` cruzado.
- **Teste para a correção:** a DSN de TEST tentando `connect` em `gestor_pecas` deve receber `permission denied`.

### BK-10 · P2 · CONFIRMADO-INSP — Não há limite global de tamanho de body

- **Área:** C (API4:2023 Unrestricted Resource Consumption)
- **Arquivo:linha:** `backend/api/main.py:653-690`. Os middlewares são GZip, CORS, TrustedHost e `request_context`, e nenhum deles limita `Content-Length`. O SOAP tem um limite próprio (positivo).
- **Impacto:** um usuário autenticado, ou o login público, pode enviar corpos grandes e prender threads e memória. Os schemas Pydantic limitam campos, mas só **depois** do parse.
- **Recomendação:** um middleware que recuse corpos acima de N KB (413), com exceções explícitas para upload.
- **Teste para a correção:** um POST de 10 MB no login deve receber 413 sem chegar ao handler.

### BK-11 · P3 · CONFIRMADO-INSP — O fuso horário vem do SO do host, e a configuração de sessão falha aberta

- **Área:** E (tempo)
- **Arquivo:linha:**
  - `app/database/database.py:133-135` (`agora_db = datetime.now()` naive);
  - `app/database/totvs_repository.py:16`;
  - `app/database/connection.py:42-76`: o TZ e o `statement_timeout` da sessão só geram um **warning** quando falham (`except Exception: pass`, marcado como nosec).
  - As 104 colunas de data são `timestamp without time zone`.
- **Impacto:** se o SO da VM estiver em outro fuso (UTC numa imagem nova, por exemplo), todos os apontamentos ficam deslocados 3 h e o OEE por turno fica errado sem nenhum erro. O Brasil não tem horário de verão desde 2019, então hoje não há ambiguidade de DST.
- **Recomendação:** um guard de startup que compare `datetime.now().astimezone().utcoffset()` com `America/Sao_Paulo` e recuse subir quando divergirem, e falha fechada no `SET TIME ZONE`.
- **Teste para a correção:** `TZ=UTC` deve impedir o startup e emitir um erro claro.

### BK-12 · P3 · CONFIRMADO-INSP — O lease do outbox (120 s) é menor que o pior lote (10 × 30 s)

- **Área:** D
- **Arquivo:linha:** `backend/api/config.py:174` (lease de 120 s); `backend/integrations/totvs_wspcp.py:58` (timeout de 30 s). O worker envia os itens sequencialmente.
- **Impacto:** com o TOTVS lento e 2 processos, o lease expira no meio do lote e outro worker reclama o mesmo item. O efeito é envio duplicado, **mitigado pelo `idempotency_key`**, e contagem de tentativas inflada.
- **Recomendação:** um lease maior que `batch × timeout` ou renovação do lease por item.
- **Teste para a correção:** um fake TOTVS com sleep de 30 s e 2 workers. Deve haver exatamente um envio por item.

### BK-13 · P3 · CONFIRMADO-INSP — `request_id` sem correlação nos logs de serviço

- **Área:** E
- **Arquivo:linha:** `backend/api/main.py:653-690`. Um UUID novo é gerado e o valor de entrada é ignorado (correto). O ID só é logado nos handlers de erro; não há `contextvar` nem filtro de logging.
- **Impacto:** não dá para seguir uma ação do operador pelos logs de `mes/` e `app/`.
- **Recomendação:** `contextvars` com um `logging.Filter` que injete o `request_id`.
- **Teste para a correção:** um log emitido num service durante a requisição deve conter o `X-Request-ID` da resposta.

### BK-14 · P3 · CONFIRMADO-INSP — Health sem separação de liveness e readiness, e `_last_error` nunca é zerado

- **Área:** E
- **Arquivo:linha:** `backend/api/routers/system.py:164-171` (retorna 503 quando o status não é "ok", o que é **positivo** e refuta a suspeita anterior); `DatabaseManager.health` nunca zera `_last_error`.
- **Impacto:** depois de uma falha transitória, o health pode continuar relatando um erro antigo. O health gate do deploy e a probe de liveness dependem do mesmo pool (BK-01).
- **Recomendação:** separar `/live` e `/ready` e zerar o erro depois de um sucesso.
- **Teste para a correção:** banco cai e volta; o health deve voltar a "ok" sem erro residual.

### BK-15 · P3 · CONFIRMADO-INSP — SigmaNEST: `TrustServerCertificate=yes` e timeout de query que falha aberto

- **Área:** C/D
- **Arquivo:linha:** `backend/integrations/sigmanest_sqlserver.py:60-160`. O `PWD` é concatenado na connection string sem escape, e uma falha ao definir o timeout só gera um warning.
- **Positivo:** conexão `readonly`, `ApplicationIntent=ReadOnly`, somente `SELECT … WITH (NOLOCK)`.
- **Impacto:** risco de MITM na rede local contra uma credencial SQL-auth. Uma query pode ficar sem timeout.
- **Recomendação:** confiar na CA interna, escapar com `{…}`, e falhar fechado no timeout.
- **Teste para a correção:** uma senha com `;` deve conectar corretamente; se o timeout falhar, a sincronização deve abortar.

### BK-16 · P3 · CONFIRMADO — 21 FKs sem índice de suporte

- **Área:** B
- **Exemplos:** `eventos_estado_recurso.evento_apontamento_id`, `qualidade_inspecoes.apontamento_id` e `template_id`, `totvs_outbox.canonical_event_id`, `chamadas.contato_id`, e as FKs `report_*`.
- **Evidência:** `pg_constraint` cruzado com `pg_index` no TEST.
- **Impacto:** `DELETE` e `UPDATE` no pai varrem o filho inteiro, e joins pela FK ficam lentos com volume.
- **Recomendação:** criar índices só nas FKs que aparecem em join ou delete (pelo EXPLAIN), não nas 21 às cegas.
- **Teste para a correção:** o EXPLAIN do join deve usar Index Scan.

### BK-17 · P3 · CONFIRMADO — `CHECK (quantidade_boa + quantidade_refugo <= quantidade) NOT VALID`

- **Área:** B (qualidade de dado)
- **Evidência:** `pg_constraint` em `apontamentos_operacionais`.
- **Impacto:** linhas históricas nunca foram validadas. O OEE/FTT de períodos antigos pode conter linhas que violam a regra.
- **Recomendação:** rodar um `SELECT` de contagem das violações no REAL (somente leitura, com aprovação) e depois `VALIDATE CONSTRAINT`.
- **Teste para a correção:** `VALIDATE` deve passar sem erro.

### BK-18 · P3 · CONFIRMADO-INSP — `/capabilities` é público e expõe metadados

- **Área:** C (API8:2023)
- **Evidência:** a varredura AST mostra a rota sem dependência de auth. Ela expõe a flag de simulação e metadados da API.
- **Impacto:** reconhecimento facilitado pelo túnel público.
- **Recomendação:** exigir sessão, ou reduzir o payload ao mínimo que o login precisa.
- **Teste para a correção:** um GET anônimo deve receber 401 ou o payload mínimo.

### BK-19 · P3 · CONFIRMADO-INSP — SOAP responde 500 para SOAPAction inválida

- **Área:** C/D
- **Arquivo:linha:** `backend/integrations/totvs_soap.py:200-275`. O default de `_fault` é 500.
- **Impacto:** um erro do cliente aparece como falha do servidor, o que polui o monitoramento. **A guarda fail-closed (F4) continua íntegra.**
- **Recomendação:** retornar 400 ou 415 com o fault SOAP.
- **Teste para a correção:** uma action inválida deve receber 4xx.

### BK-20 · P3 · CONFIRMADO-INSP — IA sem rate limit por usuário

- **Área:** C (custo/DoS)
- **Evidência:** existe `MAX_AI_MESSAGE_CHARS`, mas o cooldown só reage a um 429 do Groq.
- **Impacto:** um único gestor pode esgotar a cota do Groq para todos.
- **Recomendação:** um token bucket por usuário.
- **Teste para a correção:** N+1 chamadas na janela devem gerar um 429 local.

### BK-21 · P3 · CONFIRMADO-INSP — Schemas `common` (11) e `quality` (9) sem `extra="forbid"`

- **Área:** C (ASVS V5)
- **Evidência:** `operator`, `ai`, `reports` e `auth.LoginRequest` usam `forbid`; esses dois não.
- **Impacto:** campos extras são ignorados em silêncio, e erros de contrato do frontend passam despercebidos.
- **Recomendação:** padronizar em `forbid` nos modelos de comando.
- **Teste para a correção:** um payload com campo extra deve receber 422.

### BK-22 · P3 · CONFIRMADO-INSP — Throttle de login com dois caminhos

- **Área:** C/F
- **Arquivo:linha:** `backend/api/routers/auth.py` usa `getattr(database, "registrar_falha_login"/"limpar_falhas_login")` com fallback para o dict em memória `_login_failures`.
- **Impacto:** os testes com fakes podem exercitar o caminho em memória, e o persistente fica sem cobertura. O caminho de produção é o persistente (positivo).
- **Recomendação:** remover o fallback e usar um fake com os métodos persistentes.
- **Teste para a correção:** um teste de integração do throttle contra o PostgreSQL.

### BK-23 · P3 · CONFIRMADO — Teste de migração não hermético e 12 schemas órfãos no TEST

- **Área:** F
- **Arquivo:linha:** `tests/test_migration_chain_11_19.py:254`. A contagem em `pg_constraint` por `conname` não filtra `connamespace`.
- **Evidência:** a **única falha** da suíte (`AssertionError: 2 != 1`). O schema órfão `cadeia11a19_096c9cc3…` contém a mesma constraint. Há 12 schemas órfãos de execuções interrompidas: `gestor_test_*`, `gestor_outbox_test_*`, `gestor_ondemand_test_*`, `gestor_etapa7c_*`, `cadeia11a19_*`. **Nenhum foi apagado**; a limpeza fica para decisão do usuário.
- **Impacto:** uma falha falsa na suíte e ruído no banco TEST. **Não é bug de produto.**
- **Recomendação:** filtrar por `connamespace = to_regnamespace(schema)` e criar uma fixture de limpeza de schemas `*_test_*` com mais de 24 h.
- **Teste para a correção:** a suíte deve ficar verde com um schema órfão presente.

### BK-24 · P3 · CONFIRMADO — God-functions

- **Área:** F/A
- **Evidência** (medição AST: 1667 funções; 64 com mais de 100 linhas e 18 com mais de 200):

  | Função | Linhas | Branches |
  |---|---|---|
  | `mes/services/operator_flow.py:820 executar` | 611 | 147 |
  | `mes/services/management.py:36 get_overview` | 556 | 128 |
  | `app/database/database.py:2293 transicionar_apontamento_operador` | 433 | — |
  | `backend/api/config.py:249 from_env` | 422 | — |
  | `mes/services/frontend_facade.py:354 consulta_operacional` | 415 | 96 |
  | `mes/services/andon.py:119 build_snapshot` | 247 | 74 |

- **Impacto:** as regras MES críticas se concentram em blocos difíceis de testar isoladamente. BK-02 e BK-03 nasceram desse padrão.
- **Recomendação:** extrair por comando ou etapa, e só quando for tocar a área (não como refatoração preventiva).

### BK-25 · P3 · CONFIRMADO-INSP — Vazamento de camadas

- **Área:** A
- **Evidência:**
  - `mes/services/frontend_facade.py` importa `app.database.schema`;
  - `mes/` depende de `app.core`;
  - há uma docstring morta e uma mensagem de erro invertida em `Database`;
  - não há ciclos de import (positivo).
- **Impacto:** a camada de domínio fica acoplada à persistência.
- **Recomendação:** usar um contrato em `mes/` e o adaptador em `app/`.

### BK-26 · P3 · CONFIRMADO-INSP — Tratamento amplo de exceções

- **Área:** F/E
- **Evidência:**
  - `except Exception`: backend 37, mes 49, app 8;
  - nenhum `except:` nu;
  - `app/database/connection.py:55,76` usa `except Exception: pass`, marcado como nosec.
- **Impacto:** falhas parciais podem passar sem alerta. Relaciona-se com BK-11.
- **Recomendação:** revisar só os blocos que engolem sem log.

---

## 4. Relação com os relatórios anteriores desta pasta

| `RELATORIO.md` (25/09) | Situação no HEAD `29f5a47` |
|---|---|
| P0-01 pool de 4 conexões | **Convergente** com BK-01. O `.env` local ainda tem `PGPOOL_MAX_SIZE=4`. Com pool 10 já houve um 503 no teste de hoje. |
| P1-01 / P1-06 período e `UPPER` anulam índice | **Confirmado** (BK-06, com EXPLAIN próprio). |
| P1-04 chave do lock divergente | **Confirmado** (BK-02). |
| P1-05 TOCTOU no Início | **Confirmado** (BK-03). |
| P1-02 N+1 de nomes de operador, P1-03 paginação em Python | Não reverificados nesta rodada. **Mantidos como estão naquele relatório.** |

---

## 5. Causas sistêmicas

1. **Invariante implementado por call site, não por ponto único.** A chave de lock (BK-02), o lock ausente (BK-03), a sanitização por formato (BK-04) e os schemas sem `forbid` (BK-21) são o mesmo padrão: a regra certa existe, mas foi replicada e esquecida num dos caminhos.
2. **Um único processo como suposição implícita.** Loops, lease e check-then-act (BK-07, BK-12) estão corretos com 1 processo e deixam de estar com 2. A suposição não é imposta nem documentada no deploy.
3. **Recurso escasso compartilhado sem bulkhead.** O mesmo pool atende o operador, os dashboards e os workers (BK-01, BK-14).
4. **Testes de sistema sem asserção de cobertura.** O harness de carga e o teste de migração degradam em silêncio (BK-05, BK-23).
5. **Fronteira de ambiente frágil.** Mesmo role, mesma instância, fuso herdado do SO e dependências sem pin (BK-08, BK-09, BK-11).

## 6. Pontos positivos (com evidência)

- **Outbox transacional:** o enqueue acontece na mesma transação do evento (`database.py:2240-2266`), com `ON CONFLICT DO NOTHING` seguido de verificação e `DatabaseIntegrityError`.
- **Claim do outbox:** CTE com `FOR UPDATE OF o SKIP LOCKED` e `NOT EXISTS` por `aggregate_id`, garantindo **ordem causal por OP (F19)**. `concluir` valida `lease_owner`, e a recuperação de abandonados roda a cada ciclo (`totvs_outbox_repository.py:153,230-345`).
- **Backoff do outbox:** 60 s → 3600 s, 12 tentativas, 3 para falha de autenticação (`mes/integrations/totvs/outbox.py:55-94`). TLS verificado e timeout de 30 s.
- **Máquina de estados:** `FOR UPDATE` seguido de `can_transition` torna o **double-submit seguro**. O índice único `upper(recurso) WHERE data_fim IS NULL` garante **um estado aberto por recurso no próprio banco** (reproduzido no seed: UniqueViolation).
- **Relógio do servidor como autoridade:** `operator_flow` sempre usa `self._now()`, e o cliente não controla o horário.
- **OEE:**
  - não corta silenciosamente acima de 100% e emite `PERFORMANCE_ABOVE_LIMIT_ALERT` (`mes/analytics/oee.py`, `_performance_metric`);
  - um denominador zero vira `None` com motivo, nunca `0`;
  - a exceção "100/0/0" é **explícita** (`_no_demand_exception`), e não um efeito de `1×0×null`;
  - uma cobertura parcial de tempo padrão gera `PARTIAL`, e nenhuma cobertura gera `NOT_CONFIGURED`.
- **Autenticação:** assinatura de sessão, `session_version` para revogação, CSRF double-submit com `hmac.compare_digest`, PBKDF2 600k num limiter dedicado, cookie `samesite=strict`, throttle persistente ip:usuário que só confia em `CF-Connecting-IP` quando a origem é loopback no host público, e `GESTOR_WEB_SESSION_SECRET` obrigatório em produção.
- **SOAP TOTVS fail-closed (F4):** 503 quando desabilitado ou sem CIDR, 403 fora do CIDR ou pelo host público, `defusedxml` recusando DTD e entidades, limite de body.
- **Headers e erros:** nosniff, `X-Frame-Options: DENY`, CSP e HSTS; os erros 500 são genéricos, sem stack trace para o cliente.
- **Limites de consulta:** período máximo de 366 dias, `max_length` nas query strings, `page_size` limitado.
- **Varreduras estáticas:** bandit M+ = 0, pip-audit limpo, actions do CI com pin por SHA, gitleaks presente.
- **Deploy:** health gate de 60 s após o restart, e `.env`, `dados/` e `backups/` preservados.
- **Suíte:** 1324 de 1325 testes verdes, e a única falha é de hermeticidade do teste.

## 7. NÃO TESTADO (impede alegar 100%)

| Item | Motivo |
|---|---|
| Volume e planos de execução no **REAL** | Acesso ao REAL proibido pela regra da auditoria. O EXPLAIN usou um seed sintético. |
| Carga com `PGPOOL_MAX_SIZE=4` (valor do `.env` local) | O harness sempre usa 10 (BK-01). |
| Carga da Solda (5 setores) e do fechamento de apontamento | O harness não autentica esses perfis nem passa os gates (BK-05). |
| Runtime com múltiplos processos (BK-07, BK-12) | A quantidade de workers do uvicorn na VM não foi verificada; nenhum teste com 2 processos foi executado. |
| Queda real do TOTVS, SigmaNEST, Telegram e Groq | Só foram inspecionados o código de timeout e retry e os testes com fakes. |
| Backup e restore do PostgreSQL | Não exercitado. |
| Rollback do deploy | Não existe (BK-08). |
| Fuzz de contrato (Schemathesis) | Não executado nesta rodada. |
| `P1-02` e `P1-03` do `RELATORIO.md` | Não reverificados. |
| Frontend e navegadores (Firefox/WebKit) | Fora do escopo do backend. |
| Configuração do SO da VM (fuso, serviço) | Sem acesso à VM. |

## 8. Plano de ondas

| Onda | Itens | Critério de pronto |
|---|---|---|
| **W1 — Chão de fábrica sob carga** | BK-05 (consertar o harness **primeiro**, para medir de verdade) → BK-01 (threads × pool, bulkhead gerencial, confirmar pool da VM) | Harness com 40/40 logins e finalizações OK; 0 respostas 5xx; `acao_inicio` com p95 abaixo de 1 s com pool 4 e com pool 10 |
| **W2 — Invariantes de concorrência** | BK-02, BK-03 e depois BK-07 (lock de líder por loop) e BK-12 | Testes concorrentes com PostgreSQL verdes; um único envio por chave com 2 processos |
| **W3 — Segurança de fronteira** | BK-04, BK-10, BK-09, BK-18, BK-21, BK-15 | CSV neutralizado; 413 para corpo grande; roles separados; 422 para campo extra |
| **W4 — Operação** | BK-08, BK-11, BK-13, BK-14 | Rollback testado; startup recusa fuso divergente; `request_id` em todos os logs; `/live` e `/ready` separados |
| **W5 — Dados e performance** | BK-06, BK-16, BK-17 | EXPLAIN com índice e menos de 20 ms no seed de 600 mil; `VALIDATE CONSTRAINT` aplicado |
| **W6 — Manutenção** | BK-23 (teste hermético e limpeza dos 12 schemas órfãos, **com aprovação**), BK-22, BK-19, BK-20, BK-24, BK-25, BK-26 | Suíte 100% verde; refatoração só quando a área for tocada |

## 9. Estado final do repositório

```
git status --short
?? .freebuff/
?? "docs/auditoria_backend_2026-09-25/RELATORIO (space bunny).md"
?? docs/auditoria_backend_2026-09-25/RELATORIO_CLAUDE_2026-09-29.md
```

Nenhuma correção foi aplicada. A única alteração no repositório é este relatório. `tests/load_test/last_run_report.json` foi restaurado depois de cada execução de carga.
