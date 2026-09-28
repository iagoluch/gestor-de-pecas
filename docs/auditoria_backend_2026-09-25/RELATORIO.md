# Auditoria Total do Backend — Gestor de Peças / MES

**Data da janela:** 28/09/2026
**HEAD auditado:** `b2b297b53d5034029b0ec0773130c718450933ef` (`b2b297b`)
**Working tree:** limpa (`git status --porcelain` = 0 linhas) no início e no fim. **Nenhum arquivo versionado foi alterado.**
**Alvo:** somente TEST. `gestor_pecas` (nome do banco "operacional" no `compose.yaml` local) **não foi lido nem escrito**.
**Natureza:** diagnóstico. **Nenhuma correção de código foi aplicada**, conforme pedido.

---

## 0. Como a evidência foi obtida (e o que isso limita)

### 0.1 Ambiente

| Item | Valor |
|---|---|
| PostgreSQL | `postgres:17-alpine` no Docker local, `127.0.0.1:15432` |
| Bancos existentes | `gestor_pecas`, `gestor_pecas_test`, `gestor_pecas_test_homolog_simulacao_3_meses_20260917` |
| `GESTOR_EXPECTED_DATABASE` | `gestor_pecas_test` |
| `GESTOR_WEB_ENV` | `development` (trava `_default_database_factory` no banco de teste — F3 confirmado ativo) |

### 0.2 Banco descartável de benchmark

`gestor_pecas_test` está praticamente vazio (1 apontamento, 2 eventos de estado, 9 OPs na
outbox) e `gestor_pecas_test_homolog_simulacao_3_meses_20260917` está **inteiramente vazio**
(0 linhas em todas as tabelas). Sem volume representativo, `EXPLAIN (ANALYZE, BUFFERS)`
seria sempre um seq scan de tabela vazia — sem valor de prova.

Para isso foi criado **`gestor_pecas_test_audit_bench`**, banco **descartável**, separado,
que **não é** TEST nem REAL, semeado pelo próprio `apply_migrations` do produto
(`SCHEMA_VERSION = 51`) e depois populado com volume sintético realista:

| Tabela | Linhas |
|---|---:|
| `apontamentos_operacionais` | 245.500 |
| `eventos_apontamento_operador` | 60.000 |
| `eventos_quantidade_producao` | 39.994 |
| `eventos_estado_recurso` | 19.997 |
| `catalogo_operacoes_op` | 12.000 |
| `totvs_outbox` | 10.000 |
| `catalogo_pcp_ops` | 2.000 |
| `catalogo_recursos_pcfactory` | 60 (12 setores) |
| `operadores_apontamento` | 60 |

**O banco foi removido ao fim da janela** (`DROP DATABASE`, confirmado). Não há resíduo.

### 0.3 Limites honestos desta auditoria

- **Volume sintético, não volume de produção.** As medidas de tempo/escrita em disco são
  válidas *para o volume semeado*. A escala real da fábrica não é conhecida pelo repositório.
  Asataloaderões de P0-01 para a fábrica estão marcadas como **estimativa** e precisam de
  confirmação com o volume real.
- **Não houve teste destrutivo de indisponibilidade** de SigmaNEST, TOTVS, Telegram ou Groq
  (ver §7, "NÃO TESTADOS").
- **Não houve execução com 2+ processos** do backend (ver P2-03).
- **Suíte completa não foi rodada** (proporcionalidade). Foram rodados os 4 módulos
  diretamente afetados: **136 testes, OK** (§6.1).

---

## 1. Resumo executivo

O backend do Gestor de Peças é **excepcionalmente disciplinado nas fronteiras que mais
custam caro**: autoridade industrial, idempotência, atomicidade, proveniência de integração e
observabilidade estão acima da média. A majority das decisões difíceis está certa e está
escrita no código.

**O problema real e único desta auditoria é de capacidade, não de correção.** Existe um
**funil de 4 conexões PostgreSQL** (`PGPOOL_MAX_SIZE=4`) alimentado por uma **threadpool de
100 slots** (`sync_thread_pool_size=100`) e por **7 tasks de fundo**, e existe **uma consulta
gerencial que custa 9,4 segundos e 80 MB de I/O temporário** em uma janela de 366 dias — a
janela que o próprio `analytics_filter` aceita como máxima.

Combinados, o resultado é medido e direto: **6 telas gerenciais abertas simultaneamente
derrubam a API inteira e devolvem HTTP 503 para qualquer outra requisição concorrente** —
inclusive a ação "Início" do operador no chão de fábrica. O operador vê "o banco de dados
está indisponível" sem que o banco esteja indisponível.

Nenhum dos F1–F21 foi reaberto: **todos os 21 continuam válidos**, e esta auditoria não
encontrou evidência reproduzível que invalide nenhum deles.

### Contagem por severidade

| Severidade | Quantidade | Achados |
|---|---:|---|
| **P0** | 1 | exaustão de pool medindo 503 no chão de fábrica |
| **P1** | 9 | consulta gerencial sem índice, N+1, chave de lock divergente, TOCTOU no início, `UPPER()` anulando índices, TLS do SigmaNEST, fail-open de timeout, `NOLOCK` agregado, varredura de rede bloqueante |
| **P2** | 11 | teto de trabalho ausente, CSV sem neutralização de fórmula, capabilities sem auth, loops sem guarda cross-process, crescimento de `login_throttle`, recreação de serviço por ciclo, entre outros |
| **P3** | 11 | camada `mes/repositories` inexistente, docstring perdida, comentário de pool desatualizado, funções gigantes,contrato do alerta de OEE, entre outros |

### Scores

| Dimensão | Nota | Fundamento |
|---|:--:|---|
| **Arquitetura / Lógica MES** | **8,5 / 10** | Nenhum atalho, ciclo ou vazamento de framework no domínio. Fórmula do OEE em fonte única e versionada. −0,5 por `mes/repositories` vazio e por 4 funções com mais de 400 linhas na borda de decisão. |
| **Segurança** | **8,0 / 10** | SQL parametrizado, XXE bloqueado, CSRF em toda escrita, RBAC com falha fechada, sessão com versão revogável, throttle persistido, headers de segurança por resposta, CI com gitleaks/bandit/pip-audit. −1,0 pelo CSV sem neutralização de fórmula, −0,5 pelo `TrustServerCertificate` fixo, −0,5 por `capabilities` sem auth. |
| **Dados / Concorrência** | **7,0 / 10** | 62 tabelas, 62 PK, 56 FK, 200 índices, 538 CHECKs, nenhum índice `UPPER()` em código crítico que não tenha o par de expressões. Advisory lock, `FOR UPDATE`, `SKIP LOCKED`, lease com dono. −2,0 pela chave de lock derivada de duas formas, −1,0 pelo TOCTOU do "Início". |
| **Performance** | **4,0 / 10** | A outbox e a timeline física têm índices perfeitos (0,1–1,2 ms). A camada gerencial é o oposto: sem índice no predicado de período, N+1 de nomes, paginação pós-carga, 9,4 s + 80 MB de temp. |
| **Resiliência / Operação** | **7,5 / 10** | Migrations com advisory lock + `lock_timeout` + `statement_timeout`; graceful shutdown com devolução de itens em `SENDING`; outbox at-least-once com ordem causal; backup/restore testado. −1,5 pela falta de guarda cross-process nos loops, −1,0 pela falta de `ready` vs `live`. |
| **Testabilidade / Manutenção** | **7,5 / 10** | 79 arquivos de teste, 136 testes verdes nos módulos auditados, cobertura nominal de todos os módulos, cobertura PostgreSQL real em CI. −1,0 por 32 funções ≥110 linhas e uma de 611, −1,0 por `tests/fakes.py` com 2.990 linhas, −1,0 por `except Exception` genérico em 90 pontos (embora nenhum esteja sem log). |

---

## 2. Achados

Severidade: **P0** = perda/corrupção, bypass crítico ou **produção inviável** ·
**P1** = alto risco · **P2** = moderado · **P3** = manutenção.

---

### P0-01 — Pool de 4 conexões é esgotado por telas gerenciais e derruba a API inteira

**Severidade:** P0 · **Status:** ABERTO, reproduzido · **Área:** Dados/Concorrência + Performance

**Arquivo:linha**
- `.env`: `PGPOOL_MAX_SIZE=4`, `PGPOOL_TIMEOUT=5`
- `app/database/config.py:25` (`pool_timeout: float = 5.0`), `:157` (leitura de `PGPOOL_MAX_SIZE`)
- `backend/api/config.py:117` (`sync_thread_pool_size: int = 100`)
- `backend/api/main.py:469-471` (aplica o limite de 100 tokens no laço de eventos)
- `app/database/connection.py:96` (`self.pool.connection(timeout=self.config.pool_timeout)`)
- `backend/api/errors/__init__.py` (handler `DatabaseError` → **503**)

**Fluxo**
`GET /api/v1/andon?inicio=<366 dias>` → `analytics_filter` (aceita até 366 dias) →
`FrontendBackendFacade.consulta_operacional()` (`mes/services/frontend_facade.py:375`) →
`Database.listar_fatos_operacionais_periodo()` (`app/database/database.py:3680`) →
`self.connection()` → espera até 5 s por uma das 4 conexões → `PoolTimeout` →
`DatabaseUnavailableError` → **HTTP 503 `database_unavailable`**.

O mesmo 503 atinge `POST /api/v1/operator/actions` — o "Início", a "Parada", o "Finalizar"
do operador.

**Evidência (medida, ponta a ponta, app FastAPI real, via `httpx.ASGITransport`)**

```
pool: min=1 max=4 wait=5.0s statement_timeout=30000ms

--- 1) consumo isolado ---
  andon 1 dia          -> 200     1.834,6 ms
  andon 90 dias        -> 200    25.588,2 ms
  andon 366 dias       -> 200    41.504,7 ms
  operations 366       -> 200    15.802,6 ms
  orders 366 (25/page) -> 200    18.139,1 ms

--- 2) 6 requisicoes gerenciais de 366 dias em paralelo ---
  andon366#0     -> 200    62.808,8 ms
  andon366#5     -> 503    33.467,0 ms
  andon366#1     -> 503    33.340,9 ms
  andon366#3     -> 503    33.270,6 ms
  andon366#2     -> 503     5.183,0 ms
  andon366#4     -> 503     5.181,7 ms
  wall=62.809 ms  p50=33.306  p95=33.467  max=62.809
```

Log do servidor durante o teste, reproduzido literalmente:

```
WARNING:root:Falha controlada de banco no request ad6435c9-…: Tempo esgotado aguardando conexão PostgreSQL.
WARNING:root:Falha controlada de banco no request 49935384-…: Tempo esgotado aguardando conexão PostgreSQL.
psycopg.errors.QueryCanceled: canceling statement due to statement timeout
ERROR:root:Conexão PostgreSQL perdida
```

**Impacto**
1. **5 de 6 requisições管理和 6请求 falham com 503.** Não é degradação: é indisponibilidade.
2. O 503 diz *"O banco de dados está indisponível no momento"* (`errors/__init__.py`, handler
   `DatabaseError`). O operador no chão de fábrica recebe essa mensagem ao tentar apontar
   produção, **enquanto o banco está perfeitamente saudável**. Isso é pior que uma falha
   declarada, porque induz o operador a culpar a infraestrutura e a repetir a ação.
3. `psycopg.errors.QueryCanceled` por `statement_timeout` é capturado por
   `except OperationalError` em `connection.py:100`? Não — é `QueryCanceled`, uma subclasse
   de `DatabaseError`, **não** de `OperationalError`. Ela escapa do `except` e chega ao
   handler genérico de `Exception`, que responde **500**. O log mostra as duas coisas:
   3 conexões foram **descartadas do pool** ("Conexão PostgreSQL perdida") por causa de um
   cancelamento por timeout. Perder 3 das 4 conexões do pool por consultas longas é
   autodestrutivo.
4. **Não há `except` para `psycopg.errors.DeadlockDetected` nem `SerializationFailure`**
   em nenhum lugar do backend: um deadlock vira 500 e o operador precisa repetir a ação.
   Verificado por busca: nenhum `except` de `psycopg.errors.*` além de `UniqueViolation`
   (`app/database/database.py:12`) e `OperationalError` (`connection.py:7`).

**Causa**
Duas decisões independentes que se multiplicam:
- O **pool foi reduzido** (`PGPOOL_MAX_SIZE=4`) enquanto a **threadpool foi aumentada para 100**.
  O comentário em `backend/api/main.py:465-468` e em `backend/api/config.py:113-116` diz
  *"40 slots por padrão — bem abaixo do chão de fábrica real"*, mas o **default real é 100**.
  O comentário está desatualizado e descreve uma medição ("45 operadores simultâneos") que
  nunca foi refeita com o pool em 4.
- **Não existe teto de trabalho por requisição** em nenhuma camada gerencial: o período é
  limitado a 366 dias, mas o *custo* não é limitado (ver P1-01 a P1-03 e P2-01).

**Padrão**
Fila de recursos com `timeout` curto (5 s) alimentada por um `workload` sem cota, onde o
`timeout` é menor que o tempo de serviço. Classic "small pool + unbounded work".

**Recomendação** (nenhuma delas foi aplicada)
1. **Subir `PGPOOL_MAX_SIZE`** para a faixa real da VM (avaliar 20–30) **e** subir
   `sync_thread_pool_size` junto, nunca sozinho. O pool PostgreSQL do piloto precisa de
   `max_connections` compatível.
2. **Impor teto de custo por requisição** no `analytics_filter`: recusar (422
   `period_too_large`) quando `dias × recursos_sem_filtro` ultrapassar um orçamento, ou exigir
   `setor`/`recurso` acima de N dias.
3. **Separar "banco indisponível" de "pool saturado"**: `PoolTimeout` deve virar **429/503 com
   `Retry-After` e texto deoperational**, nunca a mensagem de banco fora do ar.
4. **Tratar `QueryCanceled`, `DeadlockDetected` e `SerializationFailure` explicitamente**,
   com um retry idempotente curto e um código de erro próprio.
5. Corrigir o comentário de `main.py:465-468` e de `config.py:113-116`.

**Teste de correção**
Com o banco semeado (245.500 apontamentos) e `PGPOOL_MAX_SIZE=20` + teto de período:
6 × `/andon` 366 dias em paralelo → **todos 200**, nenhum `QueryCanceled`, nenhum
`Conexão PostgreSQL perdida` no log, e `POST /api/v1/operator/actions` disparado durante a
carga → **200**. Registrar p50/p95/p99 antes e depois.

---

### P1-01 — `listar_fatos_operacionais_periodo` nunca usa índice: o predicado de período é um `COALESCE`

**Severidade:** P1 · **Status:** ABERTO, reproduzido · **Área:** Performance

**Arquivo:linha:** `app/database/database.py:3680-3798`, predicado em `:3756-3757`

**Fluxo**
7 consumidores chamam esta função:
`mes/services/frontend_facade.py:375` (Andon/Consulta Operacional), `:810`,
`mes/services/management.py:796`, `mes/services/industrial_analytics.py:802`,
`mes/services/operational_reports.py:141`, `mes/services/traceability.py:85`,
`mes/services/audit.py:350`.

**Evidência**

```sql
WHERE COALESCE(a.data_inicio, a.data_entrada) <= %s
  AND COALESCE(a.data_fim, %s) >= %s
```

O índice disponível é `idx_apontamentos_periodo ON (tipo_setor, data_inicio, data_fim)`.
Uma função sobre a coluna indexada **não é indexável**: o planejador não pode usá-lo.

`EXPLAIN (ANALYZE, BUFFERS)` no banco semeado, consulta real:

| Janela | Apontamentos lidos | Tempo | Spill em disco |
|---|---:|---:|---:|
| 14 dias, sem filtro | 19.996 | **1.497 ms** | 33 MB + 21 MB |
| 90 dias, sem filtro | 60.497 | **1.931 ms** | 33 MB + 15 MB |
| 366 dias, sem filtro | 245.498 | **9.391 ms** | 50 MB + 23 MB (3 workers) |
| **Só os apontamentos ATIVOS** (o que o Andon usa) | 506 | **1,6 ms** | 0 |

Plano da janela de 366 dias (trecho):

```
Parallel Seq Scan on apontamentos_operacionais a (actual time=146.789..321.217 rows=81833 loops=3)
  Filter: ((COALESCE(data_inicio, data_entrada) <= now())
        AND (COALESCE((data_fim)::timestamp with time zone, now()) >= (now() - '366 days'::interval)))
  Rows Removed by Filter: 1
Seq Scan on catalogo_pcp_ops p
Seq Scan on catalogo_operacoes_op c
Sort Method: external merge  Disk: 50016kB
Execution Time: 9391.002 ms
```

**Impacto**
- O custo cresce com **o histórico total da tabela**, não com o período pedido. `/andon` com o
  período default de 1 dia levou **1,835 s** ponta a ponta mesmo tendo retornado 1,8 KB.
- É a causa raiz do P0-01.

**Causa** — `COALESCE(data_inicio, data_entrada)` é a única forma de expressar "o fato começou
quando entrou na fila ou quando começou a produzir". Não há coluna gerada nem índice de
expressão para isso.

**Padrão** — predicado não-sargável em consulta quente e sem limite.

**Recomendação** — índice de expressão
`CREATE INDEX ... ON apontamentos_operacionais ((COALESCE(data_inicio, data_entrada)), tipo_setor)`;
ou, preferível, gravar `data_inicio` já preenchida no `INSERT` da fila; ou decompor a
consulta em duas (janela aberta × janelas fechadas) unindo com `UNION ALL`.

**Teste de correção** — o mesmo `EXPLAIN (ANALYZE, BUFFERS)` deve mostrar
`Index Scan`/`Bitmap Index Scan` em `apontamentos_operacionais`, sem `external merge Disk`,
e `Execution Time` da janela de 366 dias abaixo de 1 s com resultado idêntico
(comparar `md5` do conjunto ordenado antes/depois).

---

### P1-02 — N+1 resolvido pelo planejador: 121.000 varreduras sequenciais para nomes de operador

**Severidade:** P1 · **Status:** ABERTO, reproduzido · **Área:** Performance

**Arquivo:linha:** `app/database/database.py:3703-3712`

```sql
(SELECT operador.nome FROM operadores_apontamento operador WHERE operador.id = a.operador_inicio_id) AS operador_inicio_nome,
(SELECT operador.nome FROM operadores_apontamento operador WHERE operador.id = a.operador_fim_id)    AS operador_fim_nome,
```

**Evidência** (janela de 366 dias, 245.498 apontamentos)

```
SubPlan 1
  ->  Seq Scan on operadores_apontamento operador (actual time=0.007..0.007 rows=0 loops=245498)
        Filter: (id = a.operador_inicio_id)
        Rows Removed by Filter: 60
SubPlan 2
  ->  Seq Scan on operadores_apontamento operador_1 (actual time=0.007..0.007 rows=0 loops=245498)
        Rows Removed by Filter: 60
SubPlan 3
  ->  Aggregate (actual time=0.005..0.005 rows=1 loops=59994)
```

**Impacto**
- 2 × 245.498 = **490.996 execuções de subplano**, cada uma varrendo as 60 linhas de
  `operadores_apontamento` → **≈29,5 milhões de tuplas examinadas** só para montar duas colunas
  de texto.
- `SubPlan 3` — o `jsonb_agg` aninhado de `operadores` dentro do `json_agg` de eventos — roda
  **59.994 vezes** (uma por evento). Com `operadores_evento_apontamento` populado, cada uma
  vira um `Hash Join` + `Sort`; hoje a tabela está vazia no benchmark, então o custo aparece
  só como 59.994 execuções de planejamento — **o custo real em produção é maior que o medido**.
- É a causa raiz número 2 do P0-01.

**Causa** — subconsultas correlacionadas escritas como escalar, em vez de um `LEFT JOIN` único
sobre uma tabela de 60 linhas. A documentação do método (`database.py:3684-3688`) afirma
*"evita N+1"* — o oposto do que acontece.

**Padrão** — N+1introduzido dentro do próprio método que afirma evitá-lo; subplano em loop
escondido dentro de um agregador JSON.

**Recomendação** — um único `LEFT JOIN` de `operadores_apontamento` (duas aliases) e um
`LEFT JOIN` de `operadores_evento_apontamento` + `operadores_apontamento` para o agregado,
ambos no mesmo nível do `FROM`.

**Teste de correção** — o plano **não pode conter `SubPlan`** para nomes de operador, e
`Buffers: shared hit` da tabela de operadores deve cair de ~491.000 para a ordem de grandeza
do número de linhas de `apontamentos_operacionais` (uma varredura por hash join).

---

### P1-03 — Paginação é aplicada em Python, depois de carregar tudo

**Severidade:** P1 · **Status:** ABERTO · **Área:** Performance / DoS

**Arquivo:linha:** `backend/api/dependencies/filters.py` (`PageParams.slice`)

```python
def slice(self, items):
    start = (self.page - 1) * self.page_size
    return list(items)[start:start + self.page_size]
```

**Fluxo** — `GET /api/v1/orders?page_size=25` carrega **245.498 apontamentos** do banco e
descarta 245.475 em memória Python. Medido: **18.139 ms** e 19 KB de resposta.

**Evidência** — a resposta tem 19 KB; o trabalho, 18 s.

**Impacto** — `page_size` (limitado a 200) dá uma falsa sensação de limite. Não há nenhum
`LIMIT`/`OFFSET` no SQL de nenhuma listagem paginada. Combinado com P2-01, qualquer usuário
autenticado de gestão pode, com uma requisição, ocupar uma conexão do pool por 41 s.

**Causa** — paginação de apresentação herdada da versão desktop, não convertida para o contrato
de banco.

**Padrão** — paginação no cliente em vez do servidor.

**Recomendação** — `LIMIT`/`OFFSET` no SQL para as listagens que realmente paginam
(`/orders`, `/audit/appointments`, `/traceability/nestings`), com `COUNT(*)` de.total separado;
e para `/andon` + `/operations/overview`, que são projeções (não listas), eliminar a
paginação e aplicar o teto de custo (P2-01).

**Teste de correção** — `page_size=25` com 245.498 linhas deve produzir `Limit` no plano e
tempo < 50 ms; `EXPLAIN` deve mostrar `rows=25` no nível superior.

---

### P1-04 — A chave do advisory lock de recurso é derivada de duas formas diferentes

**Severidade:** P1 · **Status:** ABERTO, reproduzido por inspeção · **Área:** Dados/Concorrência

**Arquivo:linha**
- `app/database/database.py:4002-4011` (`_bloquear_recursos_tx`) → `resolve_resource_identity(recurso).upper()`
- `app/database/database.py:4045-4051` (`_encerrar_estado_recurso_tx`) → `resolve_resource_identity(recurso)`
- `app/database/database.py:4083-4095` (`_transicionar_estado_recurso_tx`) → `resolve_resource_identity(recurso)`
- `app/database/database.py:4257-4261` (`_abrir_intervalo_tx`) → `resolve_resource_identity(recurso)`
- **`app/database/database.py:4918-4925` (`registrar_rateio_recurso`) → `str(recurso or "").strip()` cru**

**Prova** — `app/core/resource_mapping.py:213-249` (`resolve_resource_identity`) resolve
*"Laser Ensis 3015" → "LASER1"*, *"1303" → "DOBRA3"*, *"Preparação" → "PREP"*. A sessão PostgreSQL
semeadas no benchmark tem `max_connections = 100`, `work_mem = 4MB`, `shared_buffers = 128MB`.

**Impacto** — `registrar_rateio_recurso` e `_transicionar_estado_recurso_tx` protegem **a mesma
invariante física** ("não permitir duas sessões físicas sobrepostas do mesmo recurso",
`AGENTS.md`) com **chaves de lock diferentes** quando o chamador passa um alias ou nome de
posto. O `SELECT pg_advisory_xact_lock(hashtext('LASER ENSIS 3015'))` e o
`pg_advisory_xact_lock(hashtext('LASER1'))` são travas distintas → **a exclusão mútua não vale
entre os dois caminhos**. O comentário em `registrar_rateio_recurso:4919-4921` afirma
*"Assim duas requisições Web simultâneas não conseguem transformar 60 minutos reais em duas
sessões concorrentes"* — a garantia só vale se as duas requisições usarem o **mesmo** formato
de identidade, o que não é garantido.

**Agravante** — `sessoes_recurso` **não tem** a restrição de identidade canônica que a
migration 51 criou para `eventos_estado_recurso`
(`ck_eventos_estado_recurso_codigo_canonico`, `NOT VALID`, lista de 18 nomes). A
`database.py:4947` grava `recurso` cru. Ou seja, o mesmo bug de identidade duplicada que a
migration 51 existe para impedir **ainda pode ocorrer em `sessoes_recurso`**, e essa tabela
alimenta `listar_rateios_tempo_periodo` → `ManagementService._load_rateio_summary` → OEE.

**Causa** — a resolução de identidade foi centralizada em 4 call sites e esquecida no 5º,
adicionado depois.

**Padrão** — derivação de chave de lock replicada em vez de extraída; invariant de banco
aplicado a uma tabela e esquecido na irmã.

**Recomendação** — extrair um único `_chave_de_lock_de_recurso(recurso)` em
`app/database/database.py` e usá-lo nos 5 call sites; gravar `resolve_resource_identity(...)`
em `sessoes_recurso.recurso`; e criar a constraint equivalente em `sessoes_recurso` (`NOT VALID`,
como a 51) com a lista congelada de `RESOURCE_STATE_FORBIDDEN_IDENTITIES`.

**Teste de correção** — teste de integração PostgreSQL com dois concorrentes: `registrar_rateio_recurso("Laser Ensis 3015", …)` e
`_transicionar_estado_recurso_tx(cursor, "LASER1", …)` simultâneos → o segundo **deve** obter
`ValueError("Já existe uma sessão física sobreposta para este recurso.")`; e
`SELECT count(DISTINCT resolve) FROM sessoes_recurso` deve devolver 1 linha por recurso
físico, nunca 2.

---

### P1-05 — "Início" não serializa por recurso: TOCTOU entre a checagem e o INSERT

**Severidade:** P1 · **Status:** ABERTO, reproduzido por inspeção + constraint · **Área:** Dados/Concorrência

**Arquivo:linha**
- `mes/services/operator_flow.py:982-989` (`recurso_em_uso`, **leitura** em transação própria)
- `app/database/database.py:2084-2146` (`enfileirar_apontamento_operacional`, o **INSERT**)
- Constraint: `idx_apontamento_ativo_op_setor` = `UNIQUE (upper(op), upper(tipo_setor)) WHERE status IN ('Aguardando','Em processo','Parada','Setup','Retrabalho')`

**Prova**
1. O índice único parcial **não inclui `maquina`**. Duas OPs diferentes no mesmo setor
   **passam** pela constraint.
2. `enfileirar_apontamento_operacional` **não** chama `pg_advisory_xact_lock` — diferente de
   `transicionar_apontamento_operador` (linha 2370), `_transicionar_estado_recurso_tx`
   (4093) e `registrar_rateio_recurso` (4923). É o **único** caminho de escrita de estado
   ocupante sem a trava.
3. `recurso_em_uso` roda antes, em outra conexão, e só considera status
   `{'Em processo','Parada','Setup','Retrabalho'}` (`operator_flow.py:813-815`) — **não**
   considera `'Aguardando'`, que é exatamente o status que `enfileirar_apontamento_operacional`
   grava.

**Fluxo de falha**
T1: operador A pressiona "Início" da OP‑X na máquina M.
T2: operador B pressiona "Início" da OP‑Y na **mesma** máquina M, no mesmo instante.
Ambos leem `recurso_em_uso(M)` → vazio. Ambos executam `INSERT` → **duas linhas
`'Aguardando'` na mesma máquina**, sem que nada recuse. A constraint de estado físico
(`idx_estado_recurso_aberto`, `UNIQUE (upper(recurso)) WHERE data_fim IS NULL`) protege a
timeline, mas **não** a fila de apontamentos.

**Impacto**
- **Sem corrupção de dado** (a exclusividade real é barrada no `Início` seguinte, por
  `recurso_exclusivo` em `transicionar_apontamento_operador:2360-2398`, que devolve
  `exclusive_resource_conflict`). Bom.
- Mas a **fila fica com dois apontamentos ativos na mesma máquina**, o que polui
  `listar_cartoes`, `listar_operacoes`/`_buscar_conflito_ativo`, o Andon e
  `Consulta Operacional → Recursos`, e faz o operador ver uma máquina ocupada por duas OPs.
  Isso é exatamente a classe de inconsistência que o `AGENTS.md` proíbe.

**Causa** — o guard de exclusividade foi colocado na transição de estado, e não na entrada na
fila, que é onde a corrida nasce.

**Padrão** — check-then-act em transações diferentes; invariante garantida no consumidor e não
no produtor.

**Recomendação** — `enfileirar_apontamento_operacional` deve tomar
`pg_advisory_xact_lock(hashtext(UPPER(resolve_resource_identity(maquina))))` antes do `INSERT`,
seguindo a ordem canônica de `database.py:3992-4000`; e a checagem de ocupação deve incluir
`'Aguardando'` **ou** o recorte deve ser explícito ("fila pode ter N, ocupação não pode ter 2").

**Teste de correção** — teste de concorrência PostgreSQL: 8 threads chamando
`enfileirar_apontamento_operacional` com 8 OPs distintas e a **mesma** máquina, ao mesmo
tempo; afirmar `len({row["maquina"] for row in ativos}) == 1`.

---

### P1-06 — `UPPER()` nas consultas anula os índices construídos para elas

**Severidade:** P1 · **Status:** ABERTO, reproduzido · **Área:** Dados/Performance

**Arquivo:linha + schema**

| Índice no banco | Coluna | Consulta que deveria usá-lo | Usa? |
|---|---|---|---|
| `idx_apontamentos_fila (tipo_setor, maquina, status, data_entrada)` | `apontamentos_operacionais` | `listar_apontamentos_operacionais` (`database.py:2148-2153`, `UPPER(tipo_setor)`, `UPPER(maquina)`) | **NÃO** |
| `idx_apontamentos_periodo (tipo_setor, data_inicio, data_fim)` | `apontamentos_operacionais` | `listar_fatos_operacionais_periodo` (`:3761`, `UPPER(a.tipo_setor)`) | **NÃO** |
| `idx_sessao_recurso_periodo (recurso, data_inicio, data_fim)` | `sessoes_recurso` | `registrar_rateio_recurso` (`:4928-4934`, `UPPER(recurso)`) | **NÃO** |

**Evidência (A/B lado a lado, mesma consulta, 20.000 apontamentos)**

Com `UPPER()`:
```
->  Bitmap Index Scan on idx_apontamento_ativo_op_setor
      Index Cond: (upper(tipo_setor) = 'DOBRA'::text)
    Filter: (upper(maquina) = 'R007'::text)
```

Sem `UPPER()`:
```
->  Index Scan using idx_apontamentos_fila on apontamentos_operacionais
      Index Cond: ((tipo_setor = 'Dobra') AND (maquina = 'R007') AND (status = ANY (...)))
```

E para a sessão física:
```
->  Seq Scan on sessoes_recurso
      Filter: ((upper(recurso) = 'R007') AND ...)
```

**Impacto**
- `idx_apontamentos_fila` e `idx_apontamentos_periodo` são **índices mortos** para o caminho de
  leitura gerencial, que é o mais frequente.
- `sessoes_recurso` faz **seq scan** em **toda** gravação de sessão física. A tabela só cresce
  (uma linha por sessão de rateio, sem política de retenção) — o custo cresce sem limite.
- `UPPER()` também impede o uso de índice de qualquer forma em `listar_rateios_tempo_periodo`,
  `listar_eventos_quantidade_periodo` e afins que usem o mesmo padrão.

**Observação que torna o achado incoerente:** o projeto **já fez** o certo em outros lugares —
`idx_apontamento_ativo_op_setor` é `UNIQUE (upper(op), upper(tipo_setor))`, ou seja,
**índice de expressão**; `idx_estado_recurso_aberto` é `UNIQUE (upper(recurso))`; e
`idx_qualidade_rnc_op` é `(UPPER(codigo_op), …)`. A decisão "gravar sempre em maiúsculas com
`limpa_codigo`" (`app/core/normalization.py:43` já devolve `upper()`) tornaria as três
consultas `UPPER()` **integiramente redundantes**, e os três índices voltariam a funcionar sem
nenhuma migration.

**Causa** — defesa em profundidade aplicada de forma inconsistente: `limpa_codigo` já
normaliza na escrita, mas a leitura voltou a "proteger" com `UPPER()`.

**Padrão** — predicado funcional sobre coluna já normalizada na escrita; índice de expressão
usado onde não é preciso e índice simples inútil onde é preciso.

**Recomendação** — remover `UPPER()` das consultas listadas (a invariante de caixa é
garantida por `limpa_codigo` e pelos CHECKs), **verificando antes** que nenhum caminho legado
grava minúsculas; se houver risco, trocar por índices de expressão em vez de envolver a coluna.

**Teste de correção** — `EXPLAIN` deve mostrar `Index Scan using idx_apontamentos_fila` e
`Index Scan using idx_sessao_recurso_periodo`; e um teste de invariante que faca
`assert not any(linha != linha.upper() for linha in <colunas>)` sobre o banco de teste.

---

### P1-07 — `TrustServerCertificate=yes` fixo na conexão com o SigmaNEST

**Severidade:** P1 · **Status:** ABERTO · **Área:** Segurança / IT↔OT

**Arquivo:linha:** `backend/integrations/sigmanest_sqlserver.py:72`

```python
partes = [
    f"DRIVER={{{driver}}}",
    f"SERVER={servidor}",
    f"DATABASE={banco}",
    "TrustServerCertificate=yes",      # ← literal, não configurável
    "ApplicationIntent=ReadOnly",
    f"Connect Timeout={…}",
]
```

**Fluxo** — `SigmaNestSyncService` → `SigmaNestSqlServerGateway._abrir()` (`:138-157`) →
`pyodbc.connect(self.dsn, readonly=True, autocommit=True)`. Chamado pelo ciclo automático
(`backend/api/main.py:336-363`, a cada 120 s) e pelo botão "Atualizar tarefas".

**Impacto**
`TrustServerCertificate=yes` **desliga a validação do certificado TLS**. Na fronteira IT↔OT —
uma rede que, pela própria documentação do projeto, é a que carrega o planejamento de Corte
inteiro da fábrica — isso permite **man-in-the-middle** com injeção de planos de corte
falsos. O plano de corte falso é o insumo de `apontamentos_corte` e do avanço de OP
(`_corte_concluido_sql`, `database.py:78-130`): um atacante no caminho controla **quais chapas
são consideradas cortadas** e, portanto, **quando a OP avança de etapa**.

Não há nenhuma variável de ambiente para desligar isso; é literal no código.

**Causa** — decisão de conectividade prática tomada uma vez, sem registro de risco de
fronteira OT.

**Padrão** — desabilitar verificação de segurança em fronteira de rede por conveniência, sem
chave de configuração nem alternativa.

**Recomendação** — tornar o DSN parametrizável (`SIGMANEST_TRUST_SERVER_CERTIFICATE`, default
`yes` **apenas** com aviso explícito no startup), e provisionar o certificado do SQL Server
para poder usar `no`/`verify` no piloto. Registrar a decisão no `docs/INTEGRACAO_CORTE_SIGMANEST.md`.

**Teste de correção** — teste que constrói o DSN com a variável ligada e desligada e afirma a
diferença; e um ensaio no TESTE com certificado válido provando que `TrustServerCertificate=no`
conecta quando o certificado está corretamente provisionado.

---

### P1-08 — Timeout de consulta do SigmaNEST falha **aberto** (sem limite nenhum)

**Severidade:** P1 · **Status:** ABERTO · **Área:** Segurança / Resiliência

**Arquivo:linha:** `backend/integrations/sigmanest_sqlserver.py:147-156`

```python
try:
    conexao.timeout = int(str(os.environ.get("SIGMANEST_QUERY_TIMEOUT") or "30").strip())
except (AttributeError, ValueError) as exc:
    LOGGER.warning(
        "Timeout de consulta do SigmaNEST não aplicado (SIGMANEST_QUERY_TIMEOUT): %s; "
        "consultas ficam sem limite de execução.", exc,
    )
return conexao
```

**Impacto** — se `SIGMANEST_QUERY_TIMEOUT` estiver vazio, não numérico, ou o driver não
suportar o atributo, a consulta **fica sem limite de execução**. O comentário nas linhas 144-146
explica exatamente por que isso é perigoso ("uma consulta presa … fica bloqueada
indefinidamente") e então o código aceita continuar nesse estado.

O consumidor é `asyncio.to_thread(self._executar)` (`mes/services/sigmanest_refresh.py:117`),
dentro de um `asyncio.Lock`. **Uma única query travada segura o coordenador para sempre**: o
`finally: self.state.executando = False` nunca é alcançado, o lock nunca é liberado, e o botão
"Atualizar tarefas" da tela de Corte passa a **aderir** a um ciclo eterno, recebendo
`"Sincronização já estava em andamento."` indefinidamente. O ciclo automático também para de
publicar invalidação. **A leitura de Corte fica congelada sem erro visível.**

**Causa** — `fail-open` num guard de disponibilidade, em uma fronteira onde indisponibilidade
é o cenário esperado.

**Padrão** — degradação silenciosa em caminho de dependência externa; o warning não impede o
estado perigoso.

**Recomendação** — falhar **fechado**: se o timeout não puder ser aplicado, fechar a conexão e
lançar `SigmaNestConfigurationError`, deixando a fila local valendo com mensagem de operador
(o caminho de erro de `sigmanest_refresh.py:118-128` já existe e é correto). Alternativamente,
aplicar o timeout no driver (`` + `;` no DSN: `Query Timeout=`) e validar o DSN na montagem.

**Teste de correção** — com `SIGMANEST_QUERY_TIMEOUT="abc"`, `ler_planejamento` deve levantar
`SigmaNestConfigurationError` e o coordenador deve publicar `ok=False` com
`MENSAGEM_ERRO`; o teste atual (que cobre só o caminho de sucesso) precisa ser complementado.

---

### P1-09 — `NOLOCK` (READ UNCOMMITTED) em todas as consultas, com agregação por `MAX()`

**Severidade:** P1 · **Status:** ABERTO (decisão consciente, custo não registrado) · **Área:** Integrações / Dados

**Arquivo:linha:** `backend/integrations/sigmanest_sqlserver.py:96`, `:119-121`, `:124`

```sql
FROM ProgArchive p WITH (NOLOCK)
FROM STPIPArc s WITH (NOLOCK)
LEFT JOIN Part pt WITH (NOLOCK) ON …
  AND s.ProgramName IN (SELECT DISTINCT ProgramName FROM ProgArchive WITH (NOLOCK) …)
```

**Fluxo** — `_SQL_PECAS` agrega `MAX(s.QtyInProcess)`, `MAX(s.MasterPartQty)`,
`MAX(pt.Thickness)`, `MAX(pt.Data3..Data6)` e depois `GROUP BY`. O resultado é gravado em
`catalogo_sigmanest_planos_corte` / `catalogo_sigmanest_ops` e consumido pela fila de Corte.

**Impacto**
Sob READ UNCOMMITTED o SQL Server permite **leitura suja e leitura não repetível**:
1. `MAX()` sobre linhas sujas pode devolver o valor de uma transação **não commitada** que
   depois sofre `ROLLBACK`. O valor **errado** é gravado como canônico na projeção local.
2. As duas consultas (`_SQL_PLANOS` e `_SQL_PECAS`) rodam em **instantes diferentes**, sem
   snapshot. Um plano pode existir em `_SQL_PLANOS` e ainda não existir em `_SQL_PECAS` no
   instante da subconsulta `IN` → o nesting é materializado **sem suas peças**.
   A proteção existente (`_categoria_estado_apontamento`/dedupe por
   `ArchivePacketID`, `montar_snapshot:248-258`) cobre duplicidade, **não** a falta.
3. `LEFT JOIN Part` com `NOLOCK` pode devolver `NULL` para uma peça que existe, e `MAX(NULL)`
   sobre o grupo inteiro perde a informação — `material`/`thickness` viram `""`/`None` e a
   peça é gravada sem material.

Nada disso é corrigido pela releitura sobreposta de 7 dias
(`DEFAULT_OVERLAP_DAYS = 7`, `sigmanest_sync.py`), porque a releitura lê **o mesmo estado sujo**.

**Causa** — decisão deliberada e razoável (não bloquear o sistema de origem de corte), mas
tomada **sem** snapshot nem verificação de consistência, e **sem** marca de proveniência que
diga ao gestor que a quantidade exibida é uma leitura não-confirmada.

**Padrão** — `NOLOCK` como sinônimo de "não bloqueia", ignorando "não confirma".

**Recomendação**
1. Registrar a decisão e o custo em `docs/INTEGRACAO_CORTE_SIGMANEST.md` (hoje não há).
2. Marcar a proveniência da leitura: `sigmanest_synced_at` já existe
   (`catalogo_sigmanest_planos_corte` / `catalogo_sigmanest_ops`) — expor um
   `leitura_nao_confirmada: true` no read model do Corte, para que a tela não apresente
   quantidade suja como fato.
3. Se o SQL Server oferecer snapshot isolation para o SigmaNEST, avaliar
   `READ_COMMITTED_SNAPSHOT`/`SNAPSHOT` como alternativa ao `NOLOCK`.
4. Detectar a troca de pacote: `ProgArchive` tem `ArchivePacketID`; descartar um grupo cujo
   `MAX(ArchivePacketID)` não for estável entre duas leituras consecutivas custa uma query.

**Teste de correção** — com um dublê que devolva `QtyInProcess` sujo e depois faça rollback,
o snapshot **não** deve conter o valor; e um teste de consistência que exija
`len(plano.parts) > 0` para todo plano com `TransType` de produção.

---

### P1-10 — Busca de desenho varre até 4.000 arquivos de rede dentro de rota síncrona

**Severidade:** P1 · **Status:** ABERTO · **Área:** Segurança / DoS / Performance

**Arquivo:linha**
- `mes/services/drawings.py:37` (`MAX_CANDIDATES_SCANNED = 4000`), `:205-262` (`_candidatos`, `_varrer`)
- `backend/api/routers/operator.py:490` (`drawing_file`), rota `def` (threadpool)
- `backend/api/main.py:469-471` (limite de 100 tokens)

**Fluxo** — `GET /api/v1/operator/drawings/file?op=...` → `DrawingLookupService.buscar` →
`resolver_produto` (1 consulta) → `_candidatos` → `os.walk` sobre cada raiz configurada, com
`caminho.stat()` em todo candidato, **até 4.000 arquivos**. A rota é `def`, então FastAPI a
executa na **threadpool**.

**Impacto**
1. `GESTOR_OPERATOR_DRAWING_ROOTS` aponta, no TESTE, para um diretório **local**
   (`dados/desenhos_simulacao`). Em produção o mesmo código apontará para um **compartilhamento
   de rede da engenharia**. Um `stat()` em rede pode levar **centenas de ms** quando o servidor
   de arquivos está lento, e 4.000 deles podem levar **minutos**.
2. Cada operador que abre a tela do posto **ocupa uma das 100 threads** durante a varredura
   inteira. 45 operadores abrindo o posto ao mesmo tempo (início de turno) = 45 threads
   bloqueadas em I/O de rede. Os slots restantes (55) ainda respondem, mas qualquer pico
   gerencial (P0-01) encontra as 100 ocupadas.
3. A proteção é `examinados > self.max_scanned`, mas `examinados` **só é incrementado dentro
   do laço de arquivos**. Um laço de diretórios que contenha **zero arquivos** (por exemplo uma
   árvore de pastas de rede) nunca incrementa o contador → **a varredura não é limitada**.
4. `os.walk` não segue symlink, mas **segue junction/reparse point do Windows**
   (`followlinks=False` não cobre junction). Um ciclo de junction na raiz configurada
   resulta em varredura infinita — e, pelo item 3, **sem** contador que a interrompa.

**Causa** — limite de tempo definido para uma operação cujo custo real depende de I/O de rede,
e limite de arquivos aplicado só a arquivos.

**Padrão** — "MAX Itens" como se limite de quantidade fosse limite de tempo; I/O de rede em
caminho síncrono de request.

**Recomendação** — mover a varredura para fora do request (materializar um índice de desenhos
por produto, com invalidation, como já existe para o corte), ou impor `SIGMANEST`-style
`asyncio.wait_for` + limite de tempo; e limitar também o número de **diretórios** visitados.
Como correção mínima e imediata, aplicar o mesmo padrão já existente no repositório: um
tempo-limite explícito na iteração.

**Teste de correção** — com uma raiz de desenho de teste simulando 4.000 arquivos e um
dublê de `stat` com 200 ms de atraso, a rota deve responder em menos de 2 s; e uma árvore de
diretórios sem arquivos deve terminar em menos de 5 s.

---

### P2-01 — `analytics_filter` limita o período em dias, mas não limita o custo

**Severidade:** P2 · **Status:** ABERTO · **Área:** Segurança / DoS

**Arquivo:linha:** `backend/api/dependencies/filters.py`

```python
if end - start > timedelta(days=366):
    raise AppError("period_too_large", "O período máximo por consulta é de 366 dias.", )
```

**Impacto** — 366 dias é aceito **sem** filtro de setor ou recurso. Medido ponta a ponta:
`/andon` 366 dias = **41,5 s**; `/orders` 366 dias com `page_size=25` = **18,1 s**. Quatro
requisições simultâneas = pool esgotado (P0-01). Não há `Retry-After`, não há cota por usuário,
não há registro de quem consumiu o orçamento.

A checagem de plausibilidade de data (F1 do schemathesis, `efa636a`/`aef9943`) e o teto de
366 dias estão **corretos e bem feitos** — o que falta é a terceira camada: o custo.

**Recomendação** — orçamento: `dias × (1 se sem filtro de recurso/recurso, senão 0,2)` acima
de um limite → 422 `period_too_large` com mensagem que sugira filtrar por setor. Registrar o
`tempo total gasto` por `AnalyticsFilter` e expor no Dev Observatory.

**Teste de correção** — `/andon?inicio=<366d>` sem `setor` → **422**; com `setor=Dobra` → 200
em menos de 500 ms.

---

### P2-02 — `GET /api/v1/system/capabilities` responde sem autenticação

**Severidade:** P2 · **Status:** ABERTO · **Área:** Segurança

**Arquivo:linha:** `backend/api/routers/system.py:57-88` — sem `Depends(get_current_user)`,
ao contrário de `/system/events` (que tem), `/system/simulation/clock` (que tem
`require_management_user`) e `/system/rebuild-frontend` (que tem `require_admin_user`).

**O que expõe**
- `schema_version` (51) e `contract_version` — informa a versão exata do schema a um
  atacante, que pode procurar migrations correspondentes.
- `corporate_integration`: `provider`, `configured`, `planning_read_enabled`,
  `execution_write_enabled`, `reason` — **revela se a integração TOTVS está ativa** e por quê.
- `simulation`: `enabled`, `reference_time`, `time_scale`, `running`, `paused` — revela se o
  relógio virtual está ligado, ou seja, se os números da tela são reais.
- `manufacturing_rules` completo: janelas de turno, hora extra, pausas automáticas,
  classificação de parada, e as flags `clock_blocks_appointment: false`,
  `out_of_shift_is_machine_downtime: false` etc. — o mapa completo das regras industriais
  que o AGENTS.md manda manter restrito.
- `canonical_sources` com **nomes de tabela**.

Verificado que **não** há vazamento de credencial: `totvs_production_order_status`
(`mes/services/corporate_integration.py:24-44`) só devolve booleanos e uma frase; os campos de
segredo de `WebSettings` são `field(repr=False)` e não entram no payload.

**Impacto** — superfície de reconhecimento gratuitamente accessible. Não é bypass, mas é
divulgação de arquitetura e de regras de negócio por requisição anônima, e a
`manufacturing_rules` é informação que o próprio projeto classifica como sensível.

**Causa** — rota adicionada para consumo da tela inicial antes de existir sessão, e nunca
reavaliada.

**Padrão** — endpoint "informativo" que fica sem auth porque "não faz nada".

**Recomendação** — exigir `require_andon_user` (o perfil mais baixo que já lê essas regras) ou
reduzir o payload a `contract_version` + `corporate_integration.configured` para o
pré-login. Se o pré-login for realmente necessário (a tela inicial pede `/capabilities` antes
do login?), verificar com o frontend qual é o contrato mínimo.

**Teste de correção** — `GET /api/v1/system/capabilities` sem cookie → **401**.

---

### P2-03 — Tasks de fundo sem guarda cross-process

**Severidade:** P2 · **Status:** ABERTO · **Área:** Operação / Resiliência

**Arquivo:linha:** `backend/api/main.py:479-520` (7 `asyncio.create_task` no `lifespan`);
`mes/services/sigmanest_refresh.py:73` (`self._lock = asyncio.Lock()`)

**Situação** — hoje a implantação é de **processo único** (`deploy.yml` usa NSSM com
`uvicorn` sem `--workers`; `README.md:182` idem). Não há bug hoje.

**O risco** — a proteção de `SigmaNestRefreshCoordinator` (`asyncio.Lock`, `:73`) é
**intra-processo**. A documentação em `sigmanest_refresh.py:8-10` promete *"um ciclo por vez"*.
Com um segundo processo ( `--workers 2`, dois NSSM apontando para a mesma porta em troca de
janela, um `uvicorn --reload` esquecido em produção, ou o `run_simulacao_residencia.py:96` e o
serviço rodando juntos), o Genesis **passa a ler o SigmaNEST duas vezes por ciclo** e a
publicar **duas invalidações SSE** — sem que nadaDetecte.

As demais tasks: `_telegram_bot_loop` recebe **409 Conflict do Telegram** quando outro
`getUpdates` está ativo (é a rede de segurança do próprio Telegram, não do projeto);
`_telegram_digest_loop` é protegido pela chave idempotente em `telegram_digest_envios`;
`_totvs_outbox_worker_loop` é protegido por lease + `SKIP LOCKED` (correto);
`_report_scheduler_loop` é protegido por `report_deliveries` idempotente;
`_dev_observatory_loop` só grava arquivo idempotente;
**`_shift_boundary_loop` é o único sem proteção demonstrável** — a idempotência de
`ShiftBoundaryService.apply_due` não foi verificada nesta janela (ver §7).

**Causa** — o único guard distribuído do projeto (`catalog_sync_lock`, `database.py:241-258`,
com `pg_try_advisory_lock` e commit) está **dormante**: não é chamado em nenhum caminho de
produção (confirmado na auditoria de 23/09 e reconfirmado nesta — só o teste o chama).

**Padrão** — lock em memória assumido como exclusão global.

**Recomendação** — promover `catalog_sync_lock` (ou um `pg_try_advisory_lock` dedicado) para
guard de execução das tasks de fundo, com log explícito quando uma instância **não** é a
leader. Isso também resolve o `catalog_sync_lock` dormente, que é o mesmo problema.

**Teste de correção** — subir duas instâncias do app contra o mesmo banco, com o SigmaNEST
falsamente configurado, e contar as leituras: deve haver **1** por ciclo, não 2.

---

### P2-04 — `login_throttle` cresce sem limite e guarda IP em texto puro

**Severidade:** P2 · **Status:** ABERTO · **Área:** Segurança / Dados

**Arquivo:linha:** `app/database/database.py:275-324`; `backend/api/security/login_throttle.py:10-28`;
migration 48 (`app/database/migrations.py:2245-2253`)

**Prova**
1. A chave é `f"{ip}:{username.strip().casefold()}"` (`login_throttle.py:28`) — **IP em texto
   claro**, gravado permanentemente.
2. A linha é apagada **apenas** quando (a) a **mesma** chave é lida de novo e está expirada
   (`database.py:293`) ou (b) a mesma chave **autentica com sucesso** (`:323`).
3. A migration 48 cria `idx_login_throttle_last_seen ON login_throttle (last_seen_epoch)` —
   um índice que **só faz sentido** para uma varredura de retenção por tempo. Busca no backend
   inteiro: **não existe nenhuma varredura**. O índice foi criado para algo que nunca foi
   escrito.

**Impacto**
- Varredura de nomes de usuário a partir de um único IP cria **uma linha permanente por nome**.
  Não há limite de linhas nem de crescimento.
- IP de origem (dado pessoal, no Brasil GDPR/LGPD) retido por tempo indeterminado, sem base
  declarada.
- `obter_falhas_login` faz um `DELETE` dentro do caminho de **leitura** de um GET de login
  misto com `SELECT` — um `SELECT ... ; DELETE ...` na mesma transação, o que significa que
  **toda** tentativa de login bem-sucedida abre uma transação de escrita. Verificado: a
  transação abre porque `pool.connection()` faz `with conn:` (commit on success, confirmado
  por `inspect.getsource(psycopg_pool.pool.ConnectionPool.connection)`).

**Causa** — índice de retenção criado na migration, sweep nunca implementado.

**Padrão** — estado de segurança sem política de retenção; PII sem classificação.

**Recomendação** — sweep no ciclo que já roda a cada 5 s
(`backend/api/main.py:_shift_boundary_loop`) ou em `TotvsOutboxWorker`-like próprio:
`DELETE FROM login_throttle WHERE last_seen_epoch < now() - 86400`, aproveitando o índice
existente. Guardar o IP como hash truncado com sal, ou declarar a retenção explicitamente.

**Teste de correção** — inserir 10.000 chaves com `last_seen_epoch` antigo, rodar um ciclo,
afirmar `count(*) = 0`; e confirmar que a chave não contém o IP em texto claro.

---

### P2-05 — `dev_observatory_real_dsn` cai para `DATABASE_URL` (o banco operacional) por padrão

**Severidade:** P2 · **Status:** ABERTO, mitigado · **Área:** Operação / Segurança

**Arquivo:linha:** `backend/api/config.py:655-662`

```python
dev_observatory_real_dsn=_text_option(
    env.get("GESTOR_DEVOBS_REAL_DATABASE_URL") or env.get("DATABASE_URL"),
    default="",
),
```

Combinado com `dev_observatory_enabled` **ligado por padrão** (`:627-629`).

**Impacto** — num ambiente novo, sem `GESTOR_DEVOBS_REAL_DATABASE_URL` definido, o backend
**observa o banco operacional** porque é esse o alvo de `DATABASE_URL`. Numa máquina de
desenvolvimento apontada para TESTE, isso significa abrir uma sessão no **REAL** sem ninguém
ter pedido.

**Mitigação já existente e verificada** — `backend/observability/readonly_db.py` prova, na
abertura, que a credencial não é elevada, não pode `CREATE`, e não escreve
(`CREATE TEMP TABLE` recusado). A falha é **fechada**. E, neste ambiente, o `.env` tem
`GESTOR_DEVOBS_REAL_DATABASE_URL` explicitamente preenchido (§0.1) e a role `gestor_devobs`
(`NOSUPERUSER NOCREATEDB`, `GRANT SELECT`, `default_transaction_read_only=on`) foi
provisionada em 23/09/2026 (`STATUS_ATUAL.md` §2.35).

**Resta** — o *default* ainda é "olhar o banco operacional", e `dev_observatory_enabled=True`
por padrão significa que isso acontece **sem ninguém pedir**.

**Causa** — o comentário (`:655-658`) justifica o fallback como "o alvo REAL declarado no
ambiente", o que é verdade mas inverte o default seguro.

**Padrão** — default permissivo em ferramenta de observação.

**Recomendação** — default `""` (desligado), com a variável obrigatória para ligar; manter o
`DATABASE_URL` como fallback **apenas** quando `GESTOR_WEB_ENV` for produção **e** o
`verify_read_only` passar. Registrar a conexão observada no startup (`logging.info` com o
`safe_target`).

**Teste de correção** — com `GESTOR_DEVOBS_REAL_DATABASE_URL` ausente, `WebSettings.from_env()`
deve devolver `dev_observatory_real_dsn == ""` e `dev_observatory_real` deve ficar fechado.

---

### P2-06 — Serviço de relatórios e gateway WSPCP são reconstruídos a **cada ciclo**

**Severidade:** P2 · **Status:** ABERTO · **Área:** Performance / Operação

**Arquivo:linha:** `backend/api/main.py:158-168` (`_report_scheduler_loop`) e `:187-209`
(`_totvs_outbox_worker_loop`) chamam `_build_background_scheduler(_app)` /
`_build_totvs_outbox_worker(_app)` **dentro** do `while True`.

**Impacto**
1. A cada 60 s são construídos um `FrontendBackendFacade`, um `ManagementService`,
   um `IndustrialAnalyticsService`, um `ManagementInsightsService`, um `AuditService`, um
   `TraceabilityService`, um `AndonService`, um `WeldingManagementService`, um
   `IndustrialReportService`, um `ReportMessagingService`, um `ReportScheduler` — e o
   `FrontendBackendFacade.__init__` chama `load_manufacturing_rules(db)`
   (`frontend_facade.py:120`), que é uma **consulta ao banco**. A cada 15 s, o worker da outbox
   chama `TotvsWspcpClient.from_env()`, que **relê 8 variáveis de ambiente e revalida**.
2. Qualquer cache em memória nos serviços (e `ManagementService` tem `_JanelaPrefetch`, que é
   exatamente um cache) **é destruído a cada ciclo** e nunca é aproveitado entre ciclos. O
   prefetch existe para ser reutilizado dentro de **uma** requisição; recriá-lo por ciclo
   transforma um cache de requisição em trabalho descartável.
3. `TotvsWspcpClient` é um objeto **sem estado** (cria um `httpx.Client` por envio,
   `totvs_wspcp.py:125-129`), então **não há vazamento de socket**. Verificado — este ponto
   **não** é um achado.

**Causa** — a construção foi feita dentro do builder para garantir que a configuração mais
recente do `app.state` seja usada, em vez de no `lifespan`.

**Padrão** — dependência de inicialização正确的 no lugar errado (dentro do laço em vez de fora).

**Recomendação** — construir uma vez no `lifespan`, junto dos demais `app.state.*`; recarregar
apenas o que é configurável sem reconstruir o grafo.

**Teste de correção** — contar chamadas a `load_manufacturing_rules` durante 5 minutos de
`report_scheduler_interval_seconds=60`: deve ser 1 (na construção), não 5.

---

### P2-07 — `load_manufacturing_rules` roda a cada 5 segundos, para sempre

**Severidade:** P2 · **Status:** ABERTO · **Área:** Performance

**Arquivo:linha:** `backend/api/main.py:384-386`

```python
service.rules = await asyncio.to_thread(load_manufacturing_rules, service.db)
```
dentro de `_shift_boundary_loop`, que faz `await asyncio.sleep(5.0)` (`:397`).

**Impacto** — 12 consultas/minuto = **17.280 consultas/dia**, permanentes, para ler
`parametros_turno` + histórico, com o objetivo de que uma edição administrativa
(`POST /management/shift-parameters`) entre em vigor sem reiniciar. O requisito é legítimo e
está documentado (`:381-383`); o custo é 17.280 leituras/dia para uma configuração que muda
**vezes por mês**.

Com `PGPOOL_MAX_SIZE=4`, cada uma dessas leituras é uma Das 4 conexões, 12 vezes por minuto,
somadas ao resto. Em uma janela de indisponibilidade do banco, `service = None` e o laço
**tenta reconectar a cada 5 s**, cada tentativa abrindo uma conexão.

**Causa** — ausência de cache com invalidação; o `parametros_turno` já tem
`parametros_turno_historico` e `uq_parametro_turno_versao_aberta` — a mesma informação que
`_after_op_correction` usa.

**Padrão** — polling agressivo como substituto de cache/invalidação.

**Recomendação** — cachear as regras por N segundos (30–60) **ou** publicar a invalidação pelo
`RealtimeBroker` que **já existe** (`application.state.realtime.publish("shift_boundary")`
é chamado em `:389`): o POST de `shift-parameters` publica, o laço lê.

**Teste de correção** — 1 hora de execução com `load_manufacturing_rules` instrumentado:
contagem atual ≈ 720, alvo ≤ 60.

---

### P2-08 — `503` de pool saturado é reportado como "banco indisponível"

**Severidade:** P2 · **Status:** ABERTO · **Área:** Operação / Operabilidade

**Arquivo:linha:** `app/database/connection.py:98-99`; `backend/api/errors/__init__.py`
(handler `DatabaseError`)

```python
except PoolTimeout as exc:
    raise DatabaseUnavailableError("Tempo esgotado aguardando conexão PostgreSQL.") from exc
```

**Impacto** — `PoolTimeout` (saturação, o banco está **saudável**) e `OperationalError` (o banco
**caiu**) produzem o **mesmo** código (`database_unavailable`) e a **mesma** mensagem para o
operador. Em P0-01 isso significa: um diretor abre a Visão Geral em 90 dias, o piso começa a
receber "O banco de dados está indisponível no momento", e ninguém consegue distinguir
saturação de queda. O Dev Observatory registra os dois como o mesmo `error_code`, então nem o
observatório separa.

O `log` distingue (`Tempo esgotado` vs `Conexão perdida`), mas o operador e o painel não.

**Causa** — uma única exceção para dois fenômenos operacionais opostos.

**Padrão** — colapsar causas distintas no mesmo código de erro.

**Recomendação** — `PoolSaturatedError` separado, mapeado para **429** com `Retry-After: 1`,
mensagem de operação ("O sistema está ocupado. Tente novamente em instantes.") e
`error_code: pool_saturated`. Isso também permite **alertar** por ele, que é o sinal precoce
de P0-01.

**Teste de correção** — teste que esgote o pool com `PGPOOL_MAX_SIZE=1` e afirme **429** +
`pool_saturated` (não 503 + `database_unavailable`).

---

### P2-09 — Sem tratamento de `DeadlockDetected`, `SerializationFailure` ou `QueryCanceled`

**Severidade:** P2 · **Status:** ABERTO · **Área:** Dados/Concorrência

**Arquivo:linha** — busca em `app/`, `backend/`, `mes/` por `except psycopg.errors` /
`psycopg.errors.*`: **apenas** `UniqueViolation` (`app/database/database.py:12`,
`except UniqueViolation` em `:2143`) e `OperationalError`
(`app/database/connection.py:7`, `:81`, `:100`).

**Impacto**
1. `psycopg.errors.DeadlockDetected` (SQLSTATE `40P01`) — a ordem de travas em
   `transicionar_apontamento_operador` (linha do apontamento `FOR UPDATE` em `:2343` →
   advisory de recurso em `:2370` → outras linhas `FOR UPDATE` em `:2371-2389`) **é invertida
   em relação ao documento** em `database.py:3992-4000` ("A ordem canônica … é: advisory lock
   do recurso e só depois a linha aberta"). Isto é um deadlock **estruturalmente possível**
   (ver P1-04/P1-05); hoje a probabilidade é baixa porque a exclusividade de recurso impede
   dois apontamentos ativos na mesma máquina, mas qualquer caminho legado ou de scheduler que
   produza esse estado reabre a janela. Um deadlock vira **500** e o operador precisa repetir
   a ação manualmente.
2. `SerializationFailure` (`40001`) — idem, sem retry.
3. `QueryCanceled` por `statement_timeout` — **já observado** na medição de P0-01
   (`psycopg.errors.QueryCanceled: canceling statement due to statement timeout`), chegando
   como **500**, e derrubando a conexão no pool (`ERROR:root:Conexão PostgreSQL perdida`).

**Causa** — a política de retry de `AGENTS.md` ("retries devem possuir limite") existe para a
outbox TOTVS (`next_attempt_at`, `classify_attempt`), mas **não** para a transação do operador.

**Padrão** — resiliência de entrega tratada; resiliência de **transação** não.

**Recomendação** — um único `@contextmanager transacao_com_retry(...)` em
`app/database/database.py` que reexecute transações idempotentes em `40P01`/`40001` com
backoff curto (2 tentativas, 50 ms) e **não** em `QueryCanceled`. `QueryCanceled` deve virar
504/503 com código próprio, **sem** descartar a conexão.

**Teste de correção** — teste com duas threads que criam o estado de dois apontamentos ativos
na mesma máquina e tentem a transição simultaneamente: ambos devem **ter sucesso ou receber
409**, nunca 500; e o log não pode conter `deadlock_detected`.

---

### P2-10 — `rebuild-frontend` bloqueia uma thread por até 3 minutos e serve `dist` ao vivo

**Severidade:** P2 · **Status:** ABERTO · **Área:** Operação / Disponibilidade

**Arquivo:linha:** `backend/api/routers/system.py:110-161`

**O que está certo** — `require_admin_user` + `require_csrf`; `shutil.which` + lista fixa de
argumentos, `shell=False`, com `# nosec B603` e comentário justificando (**não** há injeção de
comando); `timeout=180`; `capture_output=True` limitado a `[-4000:]`.

**O que é problema**
1. A rota é `def` → ocupa **1 das 100 threads** por até 3 minutos. Com `npm run build` real
   (Vite + `tsc -b`), o consumo é de **1 a 3 GB de RAM** e de CPU, no mesmo processo que serve
   a fábrica.
2. `web/dist` é servido **diretamente do disco a cada request** (`main.py:717-719`, sem cache).
   Durante o build, `dist/` é reescrito. Um operador ou a TV que pedirem um chunk do bundle
   durante a janela recebem **HTML/JS incompleto** — a tela branca no chão de fábrica.
3. O endpoint é idempotente do ponto de vista do resultado, mas **não** do ponto de vista de
   recurso: pode ser acionado repetidamente, e a verificação **não** trava o acesso ao `dist`.

**Causa** — build happening in-process, on a directory served live.

**Padrão** — operação de build no caminho do servidor.

**Recomendação** — build para um **diretório versionado** (`dist/releases/<timestamp>`) com um
arquivo `current` apontando para o ativo, trocado atomicamente; e `npm run build` executado
**fora** do processo (o CI já produz `web-dist` e o `deploy.yml` já o baixa como artefato —
`ci.yml`/`deploy.yml` mostram que o caminho correto **já existe**).

**Teste de correção** — acionar o endpoint e, durante o build, pedir 200 requisições a
`/assets/*.js`; todas devem devolver JS válido. Alternativamente, remover o endpoint e
usar o artefato do CI (recomendado — o endpoint existe só para conveniência de desenvolvimento).

---

### P2-11 — 403 de perfil inválido acontece **depois** de validar a senha e tocar o throttle

**Severidade:** P2 · **Status:** ABERTO · **Área:** Segurança

**Arquivo:linha:** `backend/api/routers/auth.py:104-140`

Ordem real: hash da senha (`:104-107`) → **se falhou**, grava falha (`:109-120`) → **se
passou**, `limpar_falhas_login` (`:126-133`) → **só então** `normalize_user_level` (`:134`) →
403 `user_role_invalid` (`:135-140`).

**Impacto**
1. Uma conta com `nivel` fora do catálogo tem a **senha verificada** a cada tentativa. Isso
   significa que um atacante com um `nivel` corrompido no banco (ou uma conta órfã de uma
   migration futura) ainda **consome PBKDF2-600k por tentativa** e ainda **é alvo de
   brute force** — o PBKDF2 é o controle de custo, e aqui ele é jogado fora em favor de um 403
   imediato que o atacante recebe de graça.
2. O login **sucesso** apaga o contador de falhas **antes** da recusa de perfil. Uma conta com
   perfil inválido e senha correta **nunca é limitada**.
3. O `SESSION` não é emitido (correto), mas o `422/403` de validação de `LoginRequest` (`:99-104`,
   login(2) no teste) e o `403` de perfil são **indistinguíveis** para quem mede.

**Observação relevante:** a F2 (§2.23 do `STATUS_ATUAL.md`) **fechou** o problema real — perfis
desconhecidos **falham fechados**, sem fallback. Este achado é sobre **custo e ordem**, não
sobre a autorização.

**Causa** — a checagem de perfil ficou depois da autenticação por conveniência de fluxo.

**Padrão** — autorização avaliada tarde, depois de gastar o controle de custo.

**Recomendação** — verificar o perfil **antes** do hash, com uma leitura barata
(`obter_nivel_usuario_por_nome`, que já existe em `database.py:396`) e recusar 403 sem
verificar a senha; e não limpar o throttle quando a recusa for de perfil.

**Teste de correção** — conta com `nivel='inexistente'` e senha correta: 100 tentativas
consecutivas em < 2 s (hoje levariam ~100 × 400 ms) e `login_throttle` deve **não** estar
zerado.

---

## 3. Achados P3 (manutenção)

| ID | Achado | Evidência |
|---|---|---|
| **P3-01** | **`mes/repositories/` está vazio.** O `AGENTS.md` documenta `mes/repositories` como "abstrações de persistência" e a cadeia `UI/Web → contracts/services → domain/analytics → repository abstractions → infraestrutura` depende dessa camada existir. Ela não existe: `Get-ChildItem mes/repositories -Force` retorna vazio. Na prática `mes.services.*` recebe o objeto `Database` (a fachada concreta) por injeção, e o contrato não é abstrato — é duck typing sobre a fachada. | `mes/repositories/` (vazio) vs `AGENTS.md` §Estrutura principal |
| **P3-02** | **`Database` não tem docstring.** Os dois métodos de cursor do Telegram (`:169-188`) foram inseridos **acima** da docstring de classe (`:189`), que virou uma expressão de string no meio do corpo. `help(Database)` / `Database.__doc__` retornam `None`. | `app/database/database.py:169-189` |
| **P3-03** | **Comentário de pool desatualizado.** `backend/api/main.py:465-468` e `backend/api/config.py:113-116` dizem *"40 slots por padrão"* e citam *"medido no teste de carga com 45 operadores simultâneos"*. O **default real é 100** (`config.py:117`) e o **pool é 4** (`.env`), então a medição citada não descreve a configuração atual. | `config.py:113-117`, `main.py:465-471` |
| **P3-04** | **`totvs_op_pull_timeout_seconds` lê a variável `GESTOR_TOTVS_OP_PULL_WAIT_SECONDS`.** O nome do atributo e o da variável divergem; há **duas** semânticas possíveis (timeout de uma requisição vs. espera pelo sync) na mesma linha. | `config.py:180` vs `:551-557` |
| **P3-05** | **`session_ttl_seconds` sem teto.** Usa `max(300, int(env.get(...)))` (`config.py:353`) — sem `maximum`, e `int()` sobre valor inválido gera `ValueError` cru em vez de mensagem de configuração. Todos os outros números usam `_bounded_int`. | `config.py:353` |
| **P3-06** | **Performance > 100% aparece no contrato, mas a própria métrica de OEE não se explica.** `calculate_oee` devolve o alerta `PERFORMANCE_ACIMA_DE_100` em `alerts` (`oee.py:278`), que chega ao JSON via `**oee_calculation.trace_dict()` (`management.py:545`) — correto. Mas `_oee_metric` (`oee.py:290-311`) devolve `MetricValue(118.4, AVAILABLE, "%", None)`: **sem `reason`**. Um consumidor que renderize só `metrics_dict()` mostra "OEE 118,4%" com aparência de dado confiável. O `.env` deste ambiente tem `work_mem=4MB`, e o spilling é o que produz o valor — está documentado e correto. | `mes/analytics/oee.py:270-278, 290-311` |
| **P3-07** | **`safe_text` não neutraliza `TAB`/`CR` nem espaço inicial.** `text.startswith(("=", "+", "-", "@"))` (`kit.py:111`) é a mitigação padrão e está **corretamente centralizada** (via `coerce` → `write_value`, todo o XLSX passa por ela — bom). Payload com `\t=` ou espaço inicial escaparia. Risco real baixo (esses caracteres tornam a célula texto no Excel), mas o custo de cobrir é uma linha. | `backend/api/report_workbook/kit.py:107-111` |
| **P3-08** | **`os.walk` sem proteção contra junction do Windows.** `drawings.py:259` usa `followlinks` implícito (False), que não cobre reparse point/junction. Combinado com P1-10 item 3 (contador que só conta arquivos), um ciclo de junction não é interrompido. | `mes/services/drawings.py:255-262` |
| **P3-09** | **32 funções com ≥110 linhas; 4 com ≥400.** `OperatorFlowService.executar()` = **611 linhas** (`operator_flow.py:820`); `ManagementService.get_overview()` = **556** (`management.py:36`); `Database.transicionar_apontamento_operador()` = **433** (`database.py:2293`); `FrontendBackendFacade.consulta_operacional()` = **415** (`frontend_facade.py:354`). `executar()` é onde moram **todos** os gates do operador (Setup, primeira peça, refugo, recurso divergente, etapa anterior) — é a maior superfície de risco de regressão do sistema. | medição por AST nos 14 arquivos mais grandes |
| **P3-10** | **`tests/fakes.py` com 2.990 linhas** é o maior arquivo de teste e é importado por quase tudo. Uma divergência entre o dublê e `Database` produz **falso verde** — a auditoria de 23/09 já encontrou 6 falhas de `operator.test.tsx` que eram mock, não produção. | `tests/fakes.py` |
| **P3-11** | **Sem separação `live` / `ready`.** `GET /api/v1/system/health` retorna **503** quando o banco está indisponível (`routers/system.py:172-180`). O `deploy.yml` usa esse mesmo endpoint como verificação pós-restart. Se um balanceador ou o NSSM usá-lo, uma blip do banco **reinicia o serviço**. | `backend/api/routers/system.py:172-180`, `deploy.yml` |

---

## 4. Matriz de cobertura

### 4.1 Módulos (225 arquivos Python, 2,58 MB)

| Camada | Diretório | Arquivos | Linhas (maior) | Veredito |
|---|---|---:|---|---|
| Domínio | `mes/domain/` | 8 | 473 (`manufacturing_rules.py`) | **Limpo.** Nenhum import de FastAPI/psycopg/React. Regras em funções puras com docstring de regra. |
| Analytics | `mes/analytics/` | 6 | 322 (`oee.py`) | **Limpo.** Sem dependência de framework. |
| Contratos | `mes/contracts/` | 9 | — | **Limpo.** |
| Serviços | `mes/services/` | 41 | 1.737 (`operator_flow.py`) | Fronteira limpa; 4 funções gigantes (P3-09). |
| Integrações | `mes/integrations/` | 19 | — | Boa separação; SigmaNEST com P1-07/08/09. |
| AI | `mes/ai/` | 3 | — | Limpo. |
| **Repositories** | `mes/repositories/` | **0** | — | **Camada documentada e inexistente (P3-01).** |
| HTTP | `backend/api/` | 40+ | 671 (`main.py`) | Boa composição; P2-02, P2-10. |
| Infra | `app/database/` | 19 | 6.661 (`database.py`) | Fachada monolítica por mixins; P1-01..06, P2-04..09. |
| Config/pureza | `app/core/` | 9 | 265 | **Limpo e é o módulo mais bem desenhado do repositório.** |

### 4.2 Endpoints (119, extraídos do OpenAPI real)

| Tag | Qtd | Auth (verificada) | Observação |
|---|---:|---|---|
| Andon | 1 | `require_andon_user` | Caminho de P0-01 |
| Análises | 2 | `require_management_user` | Caminho de P0-01 |
| Auditoria | 3 | `require_management_user` | `PageParams` pós-carga (P1-03) |
| Autenticação | 3 | próprio | `login/logout` com CSRF; P2-11 |
| Chamadas | 9 | operador + gestão | Escritas com CSRF |
| Consulta operacional | 5 | `require_management_user` | `stream` é SSE; resto é caminho de P0-01 |
| Corte | 5 | operador | `POST /cutting/sync` aciona o SigmaNEST |
| Destaque | 3 | operador | |
| Dev Observatory | 10 | sessão própria + CSRF | Failing closed (verificado) |
| Gestão | 17 | gestão/admin | 5 escritas, todas com CSRF |
| IA Industrial | 5 | operador | `MAX_TOOL_ROUNDS` ≤ 12, `MAX_TOOL_PERIOD` ≤ 366 d, `MAX_TOOL_RESULT_MAX_CHARS` ≤ 100 k — **bem limitado** |
| Operador | 12 | `require_operator_user` | `POST /actions` e `POST /first-piece` com CSRF; P1-10 |
| Produção | 3 | `require_management_user` | P1-03 |
| Qualidade | 12 | operador/CSRF | IDOR fechado por `QualityService._exigir_setor` |
| Rastreabilidade | 2 | `require_management_user` | P1-03 |
| Relatórios | 9 | `require_management_user` | **CSV sem neutralização de fórmula (P2 abaixo)** |
| Sistema | 6 | **parcial** | `capabilities` e `health` sem auth; `rebuild-frontend` admin+CSRF |
| Solda | 1 | `require_andon_user` | |
| **TOTVS SOAP** | 2 | **peer TCP + CIDR** | F4 verificada: falha fechada (503) sem allowlist |

#### P2-extra — `export.csv` não neutraliza fórmula (CWE-1236)

Não listado acima por severidade própria porque é副 do P2, mas é o achado de segurança mais
conreto e mais fácil de explorar do grupo 2.

**Arquivo:linha:** `backend/api/routers/reports.py:215-242`

```python
writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore", delimiter=";")
for row in rows:
    writer.writerow({key: json.dumps(value, …) if isinstance(value, (dict, list)) else value …})
```

O caminho **XLSX** é protegido (`safe_text` em `kit.py:107-111`, aplicado por `coerce` →
`write_value` → `cell.value`). O caminho **CSV** não passa por nada. `_tabular_rows`
(`reports.py:210-212`) cai em `json.dumps(encoded)` do relatório inteiro, então **todo** valor de
texto — `produto_descricao`, nome de operador, `comentario`, `motivo` — vai para o CSV cru.
O BOM `\ufeff` (`reports.py:236`) faz o Excel abrir o arquivo como CSV UTF-8, que **avalia
fórmulas**.

Um `produto_descricao` vindo do payload TOTVS com `=cmd|'/C calc'!A0` chega à célula como
fórmula quando um gestor abre o CSV no Excel. Origin: dado externo (ERP) + destino: estação de
trabalho do gestor.

**Recomendação** — reutilizar `safe_text` no `writer.writerow` (importar de
`backend.api.report_workbook.kit`), ou um `csv_sanitize` próprio; e adicionar o
`test_report_export_csv_neutraliza_formula`.

**Teste de correção** — `export.csv` de um relatório cujo campo texto é `=1+1` deve conter
`'=1+1` (ou `\"=1+1\"` conforme a política escolhida), nunca `=1+1` como primeiro caractere da
célula.

### 4.3 Tabelas (62 no banco de teste, `SCHEMA_VERSION = 51`)

| Métrica | Valor | Leitura |
|---|---:|---|
| Tabelas base | 62 | — |
| **Tabelas sem PRIMARY KEY** | **0** | ✅ |
| **Tabelas sem nenhum índice** | **0** | ✅ |
| PRIMARY KEY | 62 | 1:1 com as tabelas |
| FOREIGN KEY | 56 | — |
| UNIQUE (constraint) | 22 | + índices únicos parciais |
| CHECK | 538 | densidade alta e bem direcionada |
| **EXCLUSION** | **0** | ⚠️ ver P1-04 |
| Índices totais | 200 | — |
| Contagens NOT NULL | — | `quantidade > 0`, `data_fim >= data_inicio`, `segundos_fisicos >= 0`, `quantidade_boa <= quantidade` |

**CHECKs notáveis (verificados no banco):**
- `ck_apontamentos_quantidade_atendida_planejada CHECK (quantidade_boa + quantidade_refugo <= quantidade) NOT VALID` — **exatamente** a invariante de "Quantidade Produzida = só peças boas" do AGENTS.md, no banco. `NOT VALID` significa que trava escritas novas sem reescrever o histórico. Correto.
- `ck_eventos_estado_recurso_categoria` — a taxonomia física é fechada no banco.
- `ck_eventos_estado_recurso_codigo_canonico NOT VALID` — a migration 51. **Não replicada em `sessoes_recurso`** (P1-04).
- `eventos_quantidade_producao_tipo_check CHECK (tipo IN ('boa','refugo','retrabalho'))` — a gramática de qualidade travada no banco.
- `uq_apontamento_ativo_op_setor UNIQUE (upper(op), upper(tipo_setor)) WHERE status IN (...)` — impede dois apontamentos ativos da **mesma OP no mesmo setor**, mas **não** na mesma máquina (P1-05).
- `idx_estado_recurso_aberto UNIQUE (upper(recurso)) WHERE data_fim IS NULL` — **uma** timeline aberta por recurso. Excelente invariante.
- `uq_participacao_aberta_apontamento` **e** `uq_participacao_aberta_apontamento_legado` — dois caminhos para o mesmo invariante, porque a coluna `operador_id` é nulável (F7). Bem resolvido.
- `idx_totvs_outbox_aggregate_pending (aggregate_id, id) WHERE status <> 'SENT'` — migration 46, casa **exatamente** com a consulta de ordem causal. Índice modelado a partir da consulta, não do Conversely.

**Lacunas estruturais (não são bugs, são escolhas a registrar):**
- `eventos_quantidade_producao` **não tem** `apontamento_id` nem FK para
  `apontamentos_operacionais` (verificado no `information_schema`); liga-se por
  `op`/`numero_operacao` em texto e por `referencia_origem`. A rastreabilidade da quantidade
  canônica até o apontamento é, portanto, **textual**.
- `sessoes_recurso` e `rateios_tempo_op` não têm nenhuma restrição de exclusão de
  sobreposição (0 constraints `x` no banco). A garantia é só de aplicação
  (`registrar_rateio_recurso:4918-4937`, com advisory lock + verificação).

### 4.4 Migrations

| Item | Valor |
|---|---|
| Versão do código | `SCHEMA_VERSION = 51` (`app/database/schema.py`) |
| Versão no `gestor_pecas_test` | **51** — código e banco **alinhados** ✅ |
| Faixa | 2 … 51 (50 migrations) |
| Integridade do catálogo | `validate_migration_catalog()` (`:2400-2411`) falha **antes** de abrir transação se faltar versão — F1 fechado ✅ |
| Serialização | `pg_advisory_xact_lock(MIGRATION_LOCK_ID)` (`:2447`) antes de qualquer DDL ✅ |
| Limites | `lock_timeout` (5 s) e `statement_timeout` (60 s) por `set_config(..., true)` local à transação ✅ |
| Ambiente | `GESTOR_MIGRATION_LOCK_TIMEOUT_MS=5000`, `GESTOR_MIGRATION_STATEMENT_TIMEOUT_MS=60000` |
| DDL destrutivo | Verificado que **nenhuma** migration faz `DROP`/`TRUNCATE` (só `NOT VALID` para histórico) |
| Rollback | **Não existe** — é forward-only. Consistente com AGENTS.md, mas significa que uma migration com erro exige uma nova migration corretiva. Registrado como risco, não como achado. |

### 4.5 Workers / tasks de fundo

| Task | `main.py` | Intervalo | Guarda cross-processo | Idempotência |
|---|---|---|---|---|
| `gestor-dev-observatory` | `:400-445` | 60 s | ❌ | ✅ arquivo idempotente |
| `gestor-totvs-outbox-worker` | `:187-209` | 15 s | ✅ **lease + `SKIP LOCKED` + dono** | ✅ `idempotency_key` + `ON CONFLICT DO NOTHING` |
| `gestor-sigmanest-sync` | `:336-363` | 120 s | ❌ **só `asyncio.Lock`** (P2-03) | ✅ projeção idempotente |
| `gestor-report-scheduler` | `:158-168` | 60 s | ❌ | ✅ `report_deliveries` por idempotência |
| **`gestor-shift-boundary`** | `:366-397` | **5 s** | ❌ | ⚠️ **não verificado** (NÃO TESTADO) |
| `gestor-telegram-bot` | `:212-264` | 3 s | ⚠️ safety net do próprio Telegram (409) | ✅ `telegram_bot_cursors` (F8) |
| `gestor-telegram-digest` | `:267-314` | 300 s | ❌ | ✅ `telegram_digest_envios` |

**Observação de qualidade:** todos os 7 laços isolam `asyncio.CancelledError` e re-lançam antes
do `except Exception`, e todos fazem `logging.exception` com mensagem em português de operador.
**Nenhum laço morre em silêncio.** Esse é um padrão consistentemente bem aplicado no arquivo.

### 4.6 Integrações

| Integração | Transporte | Timeout | Autenticação | Idempotência | Recuperação |
|---|---|---|---|---|---|
| **TOTVS inbound (SOAP)** | SOAP/TCP | — | **peer TCP + CIDR**, falha fechada (503) | `hashtextextended(totvs_unique_id)` advisory (`:226`) | `totvs_op_sync_requests` + cursor |
| **TOTVS pull (GPOPSYNC)** | HTTP/REST | `…_WAIT_SECONDS` (25 s) | Basic, com guard de "credencial sem mecanismo comprovado" | `totvs_op_sync_requests` | poll `…_POLL_INTERVAL_MS` + TTL negativo |
| **TOTVS outbound (WSPCP)** | HTTP/SOAP | `…_TIMEOUT_SECONDS` (30 s) | Basic; `verify_tls` configurável | ✅ **o melhor do repositório**: `idempotency_key` determinística, `ON CONFLICT`, ordem causal por OP, lease com dono, `recover_abandoned`, `FUNCTIONAL` sem retry |
| **SigmaNEST** | ODBC/SQL Server | **connect 10 s; query 30 s, mas *fail-open*** (P1-08) | `UID`/`PWD` ou `Trusted_Connection`; **`TrustServerCertificate=yes` fixo** (P1-07) | ✅ projeção idempotente + overlap 7 d | `asyncio.Lock` (só intra-processo) |
| **Telegram** | HTTPS | 30 s | token; ACK validado em `sendMessage`/`editMessageText`/`answerCallbackQuery` | ✅ cursor persistido | digest por chave lógica |
| **Groq** | HTTPS | 60 s | `GROQ_API_KEY` | n/a | `AIRateLimitState` + `to_thread` |
| **Arquivos (desenhos)** | rede/FS | ❌ **nenhum** (P1-10) | nada | n/a | ❌ **inexistente** |

### 4.7 Testes

| Item | Valor |
|---|---|
| Arquivos de teste | 79 (+ `fakes.py` com 2.990 linhas) |
| Módulos de produção sem cobertura nominal | **0** (heurística por nome) |
| **Validação desta auditoria** | `unittest tests.test_operator_flow tests.test_manufacturing_rules tests.test_industrial_analytics tests.test_totvs_outbox` → **`Ran 136 tests in 88.247s — OK`** |
| Cobertura PostgreSQL | Real, não mockada (o teste da outbox loga "Conclusão do item … descartada: a reserva não pertence mais ao worker w-lento", o que só sai de um lease real) |
| CI | `.github/workflows/ci.yml`: `unittest discover` + **serviço PostgreSQL 17** + `TEST_DATABASE_URL` + `GESTOR_EXPECTED_DATABASE` + `TZ: America/Sao_Paulo` — os testes de banco **rodam no CI** ✅ |
| CI segurança | `gitleaks` (histórico completo, digest fixo), `pip-audit`, `bandit -ll` **bloqueante**, `npm audit --audit-level=high` com `if: always()` |
| CI frontend | `npm ci` + `npm run build` + `npm run test` |
| E2E | `e2e.yml` com Playwright/Chromium contra preview self-contained |
| Actions | **Todas com pin por digest de commit** (`uses: actions/checkout@11d5960a…` etc.) ✅ |

---

## 5. O que está **certo** (não mexer)

Registrado porque a próxima onda de correção não deve tocar aqui:

1. **`mes/domain`, `mes/analytics` e `mes/contracts` não importam FastAPI, psycopg, SQLAlchemy nem React.** Verificado por busca em `app/`, `backend/`, `mes/`. A camada mais baixa é realmente a mais baixa.
2. **A fórmula do OEE existe em um lugar só** (`mes/analytics/oee.py`), com `OEE_RULE_VERSION = "corporativa-2026-09-24"` e `OEE_CONTRACT` publicado no payload. Nenhum consumidor recompõe. `_oee_metric` propaga `PARTIAL` corretamente.
3. **Performance > 100% não é truncada.** O valor bruto é devolvido com `availability=AVAILABLE`, um `reason` explicando e o alerta `PERFORMANCE_ACIMA_DE_100` no payload. Isso é o oposto de "esconder o problema" e está documentado no código.
4. **`PhysicalConsolidatedSegment` nunca escolhe um vencedor por inferência.** Estado divergente no mesmo instante → `EventCategory.UNKNOWN` + `state_conflict=True`; classificação de parada divergente → `UNPLANNED` (`physical_time.py:255-272`). Correto e raro.
5. **`merge_intervals` é fonte única** (`mes/analytics/intervals.py`) para calendário e para tempo físico, com o comentário explicando que "manter uma cópia por módulo já produziu duas definições idênticas".
6. **A outbox TOTVS é o melhor código do repositório.** `FOR UPDATE SKIP LOCKED`, lease com dono e expiração, guarda de lease na conclusão (devolve `None` em vez de sobrescrever), ordem causal por OP com índice parcial correspondente, `recover_abandoned` que preserva a `idempotency_key`, `FUNCTIONAL` que não faz retry, `_notify_error` best-effort que não derruba o ciclo, e `_truncate` de 2.000 chars nas mensagens de erro para o payload não virar dump.
7. **Migration 51 usa `NOT VALID` com lista congelada** e um teste que exige migration nova quando a lista crescer. É o padrão certo para não reescrever histórico.
8. **`resolve_resource_identity` é uma fonte única real**, com alias oficial, nome de tela, e posto compartilhado (`ROBO P`/`ROBO S` → "Robô 1") tratado explicitamente para não adivinhar. O único furo é `registrar_rateio_recurso` (P1-04).
9. **`trusted_db.readonly_db` falha fechado** e verifica privilégios efetivos, não apenas `default_transaction_read_only` (STATUS_ATUAL §2.32, verificado no código).
10. **O receptor SOAP valida o peer TCP**, não `Host` nem `X-Forwarded-For` (F4). Verificado em `backend/integrations/totvs_soap.py` e no router.
11. **`session_version` revoga tokens antigos** sem relogar (F5) e o **throttle é persistido e compartilhado entre workers** (F6).
12. **`Database()` sem argumento é travado** para bancos sem "test" no nome, e `_default_database_factory` só alcança o operacional com `GESTOR_WEB_ENV` em produção (F3). `load_postgres_config` exige `GESTOR_EXPECTED_DATABASE` literal (F7/§2.25).
13. **`require_csrf` em toda rota de escrita** — conferido nas 119 rotas.
14. **A família `except Exception` é honesta.** 90 ocorrências, **zero `except:`** puro, e todas com `logging.exception`/`warning` no contexto. Nenhum engole erro em silêncio.
15. **`# nosec` só onde há justificativa escrita ao lado** (B105/B110/B603/B404/B608), sempre com o motivo. `bandit -ll` é bloqueante no CI e a documente que os 44 achados anteriores foram triados.
16. **`anyio.to_thread` em todo caminho bloqueante novo** (login, bot, digest, relatório, AI, sync) e `CapacityLimiter` dedicado ao PBKDF2.
17. **`validated_business_datetime`** é o contrato único de data (F/schemathesis) e rejeita ano implausível com 422, não 500.
18. **`safe_text` no XLSX** é centralizado e aplicado por todo caminho de escrita de célula.
19. **O comentário de `reservar_lote_outbound_totvs`** (`:255-258`) explica a ordem causal **na própria consulta** — o SQL é legível como regra.
20. **Zero `TODO`/`FIXME`/`XXX`/`HACK`/`NotImplementedError` reais** no backend (as 30 ocorrências são a palavra portuguesa "todo").

---

## 6. Validação executada

### 6.1 Testes (proporcional, apenas os módulos auditados)

```
$ .\.venv\Scripts\python.exe -m unittest tests.test_operator_flow tests.test_manufacturing_rules \
    tests.test_industrial_analytics tests.test_totvs_outbox
..............................................................................................
.............................................Conclusão do item 1 da outbox TOTVS descartada: a reserva não pertence
mais ao worker w-lento (lease expirado ou item re-reservado).
.
----------------------------------------------------------------------
Ran 136 tests in 88.247s

OK
```

### 6.2 Imports principais

```
backend.api.main, app.database.database, app.core.operator_sectors, app.core.permissions,
mes.services.operator_flow, mes.services.cut, mes.services.task_lookup, mes.services.production,
mes.services.operational_reports, mes.integrations.totvs.service
```
— todos importados com sucesso durante a construção do app no §4.2 e no ensaio de carga.

### 6.3 EXPLAIN (ANALYZE, BUFFERS)

Executado no banco descartável semeado, com `work_mem=4MB`, `shared_buffers=128MB`,
`max_connections=100`. Resultados consolidados no §P1-01, P1-02, P1-06 e em §7.

### 6.4 Ensaio de carga ponta a ponta

App FastAPI real (`create_app`) via `httpx.ASGITransport`, banco semeado, pool e threadpool
com os valores **exatos do `.env` do ambiente**. Resultados no §P0-01.

### 6.5 Higiene

```
$ git rev-parse HEAD
b2b297b53d5034029b0ec0773130c718450933ef
$ git status --porcelain | Measure-Object   →  Count: 0
$ git diff --stat                          →  (vazio)
```

### 6.6 Limpeza

`gestor_pecas_test_audit_bench` **removido** (`DROP DATABASE`). Bancos restantes, confirmados:
`gestor_pecas`, `gestor_pecas_test`, `gestor_pecas_test_homolog_simulacao_3_meses_20260917`,
`postgres` — exatamente os de antes da janela.

---

## 7. **NÃO TESTADOS** (prova que falta; nenhum achado acima depende só disto)

| # | O que não foi provado | Por que importa | Como provar |
|---|---|---|---|
| NT-1 | **Volume real da fábrica.** Todas as medidas de tempo/espillagem são para 245.500 apontamentos sintéticos em 366 dias. O volume real é desconhecido. | A severidade de P0-01 depende dele. | `pg_total_relation_size` e `pg_stat_user_tables` no banco operacional (somente leitura), ou a contagem de `apontamentos_operacionais` do relatório de turno. |
| NT-2 | **`ShiftBoundaryService.apply_due` é idempotente sob 2 processos.** | Se não for, dois processos aplicam a mesma pausa/limite duas vezes. | Subir 2 instâncias com relógio de simulação; contar transições em `eventos_estado_recurso` para o mesmo instante. |
| NT-3 | **Deadlock real em `transicionar_apontamento_operador`.** A ordem de travas é invertida em relação ao documento, mas a janela só abre se já existirem 2 apontamentos ativos na mesma máquina — o que o código impede. | P2-09 | Forçar o estado (2 apontamentos ativos na mesma máquina) em transação separada e então disparar transições concorrentes. |
| NT-4 | **Fallo do `SIGMANEST_QUERY_TIMEOUT` real** (não apenas a exceção de `int()`). | P1-08 | `SIGMANEST_QUERY_TIMEOUT="abc"` contra o gateway; confirmar que `ler_planejamento` trava. |
| NT-5 | **Volume real do SigmaNEST.** `_SQL_PECAS` faz `GROUP BY` sobre `STPIPArc` com `IN (SELECT DISTINCT ...)` sob `NOLOCK`. Não há medição do plano no SQL Server. | P1-09, e a afirmação "não bloqueia o sistema de origem" merece prova. | `SET STATISTICS IO, TIME ON` com o plano real de execução no SigmaNEST (somente leitura). |
| NT-6 | **Timing de `os.walk` em compartilhamento de rede real.** | P1-10 | Medir em `GESTOR_OPERATOR_DRAWING_ROOTS` apontando para a raiz de produção. |
| NT-7 | **Comportamento com 2+ processos do backend.** | P2-03 | `uvicorn --workers 2` no TESTE com contagem de leituras do SigmaNEST. |
| NT-8 | **Volume de `sessoes_recurso` em produção.** O seq scan de P1-06 é inofensivo com 0 linhas e caro com milhões. Não há política de retenção para `sessoes_recurso` nem `rateios_tempo_op`. | P1-06 | Contagem de linhas no operacional (somente leitura). |
| NT-9 | **Revisão de dependências do frontend.** Fora do escopo desta auditoria (backend). | — | `npm audit` já roda no CI com `--audit-level=high`. |
| NT-10 | **Rastreabilidade por texto** de `eventos_quantidade_producao` → `apontamentos_operacionais` em dados reais (15% de divergência de código de produto entre Protheus e SigmaNEST já é fato registrado). | Qualidade da rastreabilidade | Amostra de 100 OPs comparando `codigo_op` gravado vs. canônico. |
| NT-11 | **Comportamento do pool sob `max_connections` da VM do piloto.** O `compose.yaml` local tem 100; a VM piloto é outra história. | P0-01 | Medir `max_connections` e `PGPOOL_MAX_SIZE` na VM. |
| NT-12 | **`GET /api/v1/system/capabilities` realmente sem auth em runtime.** Lido no código; não exercitado por HTTP nesta janela. | P2-02 | `curl` sem cookie contra a instância. |

---

## 8. Causas sistêmicas

Os 21 achados P0–P2 não são 21 problemas. São **5 causas**.

### C-1 — Não existe orçamento de trabalho por requisição
O único limite é **dias** (`≤ 366`). Não há limite de *linhas lidas*, *bytes de temp*,
*segundos de CPU* ou *conexões ocupadas*. `PageParams` limita o que é **mostrado**, não o que é
**feito** (P1-03). Sintoma: P0-01, P1-01, P1-02, P1-03, P2-01.
**Como fechar:** um `WorkBudget` na dependência de filtro, contado no repositório e recusado
com 422 antes de a consulta rodar.

### C-2 — A invariante de identidade do recurso tem duas languages
`resolve_resource_identity` é a fonte única, mas: o advisory lock deriva a chave dela em 4
call sites e **não** no 5º (P1-04); a migration 51 proíbe nome de posto em
`eventos_estado_recurso` e **não** em `sessoes_recurso`; as consultas usam `UPPER()` mesmo
depois de `limpa_codigo` já normalizar na escrita (P1-06).
**Como fechar:** um único `_identidade_e_lock_de_recurso(recurso)` usado por escrita, por lock
e por consulta; e a constraint replicada na tabela irmã.

### C-3 — Resiliência tratada onde é fácil e ausente onde é crítica
A outbox tem lease, backoff, idempotência, replay e notificação. A **transação do operador** não
tem retry de deadlock, nem de serialização, nem de cancelamento, e cada falha vira 500 (P2-09).
**Como fechar:** um `@contextmanager transacao_com_retry` para transações idempotentes e
`error_code` próprio para `PoolTimeout` (P2-08).

### C-4 — Configuração por variável de ambiente sem default seguro
`dev_observatory_real_dsn → DATABASE_URL` (P2-05), `TrustServerCertificate=yes` literal
(P1-07), `dev_observatory_enabled=True` por padrão, `PGPOOL_MAX_SIZE=4` no `.env` contra
`max_pool_size=10` no código. Cada uma dessas linhas é uma decisão de infraestrutura tomada
num arquivo de ambiente sem nenhum teste que a fixe.
**Como fechar:** os defaults que apontam para o **operacional** ou para **sem proteção** viram
opt-in explícito; e o `docker-compose`/NSSM do piloto passa a ser testado.

### C-5 — I/O de rede dentro do caminho de request
Desenhos de engenharia (P1-10) e leitura do SigmaNEST (P1-09) acontecem dentro de `def` que
FastAPI põe na threadpool. Ambos são **I/O de rede de latência não acotada** dentro do
orçamento de threads que serve o chão de fábrica.
**Como fechar:** índice materializado (o padrão já existe para o Corte) ou, no mínimo, um
tempo-limite explícito.

---

## 9. Plano por ondas

Nenhuma linha abaixo foi executada. É ordem proposta.

### Onda 0 — Contenção de recurso (P0-01) · ~1 dia
O objetivo é **fazer o chão de fábrica parar de receber 503**.

1. `PGPOOL_MAX_SIZE`: 4 → 20 (+ `max_connections` na VM piloto), e `sync_thread_pool_size`
   coerente. **Medir antes/depois com o ensaio de carga do §6.4** — que é exatamente o
   instrumento que já existe.
2. `PoolTimeout` → `PoolSaturatedError` → **429** + `Retry-After` + `error_code: pool_saturated`
   (P2-08). O operador passa a ver "o sistema está ocupado", não "o banco caiu".
3. `QueryCanceled` / `DeadlockDetected` / `SerializationFailure` tratados explicitamente, com
   retry idempotente curto e **sem** descartar a conexão (P2-09).
4. Corrigir os comentários de `main.py:465-468` e `config.py:113-116` (P3-03).

**Critério de pronto:** 6 × `/andon` 366 dias em paralelo → 6× 200; `POST /operator/actions`
durante a carga → 200; zero `QueryCanceled` e zero `Conexão PostgreSQL perdida` no log.

### Onda 1 — O custo da camada gerencial (P1-01, P1-02, P1-03, P2-01) · ~2-3 dias
O objetivo é **fazer o Andon e a Consulta Operacional não pagarem pelo histórico inteiro**.

1. Índice de expressão para `COALESCE(data_inicio, data_entrada)` **ou** `data_inicio` já
   preenchida no `INSERT` da fila (P1-01).
2. `LEFT JOIN` de `operadores_apontamento` no lugar dos dois subplanos; `LEFT JOIN` de
   `operadores_evento_apontamento` no lugar do `SubPlan 3` (P1-02).
3. `LIMIT`/`OFFSET` no SQL das listagens que paginam; para as projeções, teto de custo (P1-03).
4. Orçamento de trabalho no `analytics_filter`: 366 dias **sem** filtro de setor → 422 (P2-01).
5. **Andon/Consulta Operacional**: trocar o over-fetch por
   `listar_apontamentos_operacionais(somente_ativos=True)` + `listar_estados_recurso_atuais`,
   que medem 1,6 ms e 0,1 ms. Isto é a mudança de maior retorno: **~5.700×** no caminho do
   Andon.

**Critério de pronto:** `EXPLAIN` sem `SubPlan` de nome de operador e sem `external merge
Disk`; `/andon` 1 dia < 300 ms com resultado **byte-idêntico** (comparar o JSON ordenado
antes/depois); `/andon` 366 dias recusado ou < 1 s.

### Onda 2 — Integridade de concorrência e identidade (P1-04, P1-05, P1-06) · ~2 dias

1. `_identidade_e_lock_de_recurso()` único, usado nos 5 call sites; gravar
   `resolve_resource_identity` em `sessoes_recurso.recurso` (P1-04).
2. Migration 52: constraint de identidade canônica em `sessoes_recurso` (`NOT VALID`, lista
   congelada, teste que exige migration nova quando a lista crescer — **o mesmo padrão da 51**).
3. `enfileirar_apontamento_operacional` toma o advisory lock do recurso antes do `INSERT` (P1-05).
4. Remover `UPPER()` das consultas que o torna redundante (P1-06), depois de um teste de
   invariante de caixa sobre o banco.

**Critério de pronto:** 8 threads em `enfileirar_apontamento_operacional` com a mesma máquina
→ 1 apontamento ativo; `sessoes_recurso` sem nome de posto; `EXPLAIN` usando
`idx_apontamentos_fila` e `idx_sessao_recurso_periodo`.

### Onda 3 — Fronteira IT↔OT (P1-07, P1-08, P1-09) · ~2 dias (+Provisionamento)

1. `TrustServerCertificate` parametrizável, com aviso explícito no startup; provisionar
   certificado no SigmaNEST para poder desligar (P1-07).
2. Falhar **fechado** quando o timeout de query não puder ser aplicado (P1-08).
3. Registrar a decisão de `NOLOCK` + o custo em `docs/INTEGRACAO_CORTE_SIGMANEST.md` e expor
   `leitura_nao_confirmada` no read model do Corte (P1-09).

**Critério de pronto:** DSN nos dois modos; `SIGMANEST_QUERY_TIMEOUT="abc"` →
`SigmaNestConfigurationError` e fila local preservada com mensagem de operador; `NOLOCK`
documentado com o risco e a alternativa.

### Onda 4 — Superfície de rede e de segurança (P1-10, P2-02, P2-extra CSV, P2-11) · ~2 dias

1. Índice de desenhos materializado (ou tempo-limite explícito) e limite de diretórios (P1-10).
2. `capabilities` exige `require_andon_user` (P2-02).
3. `safe_text` no `export.csv` (P2-extra) + teste.
4. Perfil verificado **antes** do PBKDF2; throttle não limpo quando a recusa é de perfil (P2-11).
5. Sweep de `login_throttle` + IP com hash (P2-04).

**Critério de pronto:** `capabilities` sem cookie → 401; CSV com `=1+1` → célula neutralizada;
100 logins de perfil inválido < 2 s; `login_throttle` esvazia por retenção.

### Onda 5 — Operação e manutenção (P2-03, P2-05, P2-06, P2-07, P2-10, P3-01..11) · ~3 dias

1. Promover `catalog_sync_lock` (hoje dormente) para guard de leader das tasks de fundo (P2-03).
2. `dev_observatory_real_dsn` com default `""` (P2-05).
3. Construir os serviços de fundo **uma vez** no `lifespan` (P2-06).
4. Cache/invalidação das regras de turno em vez de polling de 5 s (P2-07).
5. `rebuild-frontend` para build fora do processo com troca atômica de `dist` (P2-10) — o CI já
   produz o artefato; o caminho correto já existe.
6. `/health/live` + `/health/ready` (P3-11).
7. Camada `mes/repositories`: **decidir** — implementar a abstração ou corrigir o `AGENTS.md`
   para descrever o que existe (P3-01). Recomendo **corrigir o documento**: a injeção da
   fachada `Database` por duck typing é simples e funciona.
8. Higiene: docstring de `Database` (P3-02), comentários de pool (P3-03), nomes de variável
   (P3-04), `session_ttl_seconds` com teto (P3-05), `reason` no OEE > 100% (P3-06), `safe_text`
   com TAB/CR (P3-07), guarda de junction (P3-08), `/health` (P3-11).

**Prioridade dentro da onda 5 (se houver só tempo para parte):** 6 → 3 → 4 → 1. O item 7
(P3-01) é uma decisão, não trabalho.

### Onda 6 — Manutenção estrutural (P3-09, P3-10) · sob demanda
`OperatorFlowService.executar()` com 611 linhas é a maior superfície de regressão do sistema e
recebeu 12 waves de regra. Dividir em `_*_pre_conditions()`, `_*_authorization()`,
`_*_effects()` — **sem mudar nenhuma decisão** — é o único trabalho que reduz risco ao longo do
tempo. Fakes de 2.990 linhas: extrair as invariantes compartilhadas.

---

## 10. Invariantes F1–F21

**Nenhum foi reaberto.** Nenhum achado desta auditoria enfraquece qualquer um deles; ao
contrário, P1-04 e P1-05 mostram que a **exclusividade de recurso (F12)** e a
**identidade canônica (F12/commit `3ec7ddf`)** são garantidas no caminho de transição mas **não**
no caminho de entrada na fila nem no caminho de rateio. Ou seja: F12 está *fechado* no que foi
auditado e *lacuna* no que não foi. As duas lacunas são as Onda 2.

| Item | Status | Observação desta auditoria |
|---|---|---|
| F1 SCHEMA_VERSION | **CORRIGIDO E PROVADO** | `validate_migration_catalog()` falha antes da transação; código 51 = banco 51. **Confirmado nesta janela.** |
| F2 normalização de papéis | **CORRIGIDO E PROVADO** | `normalize_user_level` falha fechado; 403 verificado em runtime. Ordem de verificação é P2-11 (custo, não autorização). |
| F3 caminho do banco de produção | **CORRIGIDO E PROVADO** | `_default_database_factory` + `Database()` travado sem "test". **Confirmado nesta janela.** |
| F4 autenticação do receptor SOAP | **CORRIGIDO E PROVADO** | Peer TCP, falha fechada. Segue valendo; a ativação depende do CIDR (§3 item 8 do STATUS_ATUAL). |
| F5 revogação de sessão | **CORRIGIDO E PROVADO** | `session_version`. |
| F6 throttle do login | **CORRIGIDO E PROVADO** | Persistido e compartilhado. **Ressalva nova (P2-04):** sem retenção. |
| F7 identidade do operador | **CORRIGIDO E PROVADO** | Dois índices únicos (novo + legado) cobrem os dois caminhos. |
| F8 cursor do Telegram | **CORRIGIDO E PROVADO** | `telegram_bot_cursors`. |
| F9 papel/CSRF do Dev Observatory | **CORRIGIDO E PROVADO** | Falha fechada verificada. **Ressalva nova (P2-05):** o *default* do DSN. |
| F10/F11 refugo e 1ª peça | **CORRIGIDO E PROVADO** | `REFERENCIA_PRIMEIRA_PECA` + `PRIMEIRA_PECA_REPROVADA` como defaults na autorização. |
| F12 exclusividade de recurso | **CORRIGIDO E PROVADO** | **Lacuna de cobertura (P1-04, P1-05):** garantida na transição, ausente na entrada na fila e no rateio. |
| F13 escritores do calendário | **CORRIGIDO E PROVADO** | 5 rotas administrativas com CSRF. |
| F14 crachá de exceção | **CORRIGIDO E PROVADO** | `autorizador_retrabalho` exigido, badge apenas ativo não autoriza. |
| F15 `parametros_turno` | **CORRIGIDO E PROVADO** | Ressalva de custo: P2-07. |
| F16 catálogo de setores/Andon | **CORRIGIDO E PROVADO** | — |
| F17 teto de produção | **CORRIGIDO E PROVADO** | `ck_apontamentos_quantidade_boa_planejada` no banco. |
| F18 ciclo de vida da OP no TOTVS | **RECLASSIFICADO / NÃO ERA BUG** | Não reaberto. |
| F19 ordem causal da outbox | **CORRIGIDO E PROVADO** | Índice parcial casa com a consulta; medido 1,175 ms. |
| F20 deploy preserva runtime | **CORRIGIDO E PROVADO** | — |
| F21 backup/DR | **CAPACIDADE IMPLEMENTADA** | Operação depende da infra; fora do escopo do repositório. |

---

## 11. Estado final

```
$ git rev-parse HEAD
b2b297b53d5034029b0ec0773130c718450933ef

$ git status --porcelain
(sem saída — árvore limpa)

$ git diff --stat
(sem saída)
```

**Nenhum arquivo do repositório foi modificado.** O único diretório criado foi
`docs/auditoria_backend_2026-09-25/` (este relatório). O banco
`gestor_pecas_test_audit_bench` foi criado, usado e **removido**. Nada foi commitado, nada foi
pushado.
