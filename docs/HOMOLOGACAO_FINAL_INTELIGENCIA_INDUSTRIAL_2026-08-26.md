# Homologação Final — Inteligência Industrial

> **HISTÓRICO — INSTÂNCIA ENCERRADA.** A instância/banco de homologação citados abaixo foram usados como evidência em 26/08/2026 e não são o ambiente atual. O banco histórico foi removido em 27/08/2026 após dump restaurável; o TESTE oficial é `gestor_pecas_test`. Consulte `ROADMAP.md`.

**Data:** 26/08/2026
**Escopo:** homologação, estabilização e documentação. Nenhuma funcionalidade nova foi adicionada.
**Documento de referência:** este arquivo substitui os relatórios intermediários como estado atual do sistema.

---

## 1. Instância homologada

| Item | Valor |
|---|---|
| URL | `http://127.0.0.1:8001/` |
| PID | **25528** |
| Banco | `gestor_pecas_test_homolog_simulacao_3_meses_20260824` |
| Schema | **15** |
| Relógio de referência | `2026-08-24T08:32:00` (`GESTOR_SIMULATION_MODE=true`) |
| Guarda de banco | `GESTOR_EXPECTED_DATABASE` apontando para o banco de homologação |
| Automação de relatório | desabilitada (`GESTOR_REPORT_AUTOMATION_ENABLED=false`) |

Todas as validações desta execução usaram exclusivamente a porta 8001.

### 1.1 Achado de configuração — [CONFIRMADO]

O backend **não** resolve o DSN por `DATABASE_URL`. `Database()` sem DSN explícito chama
`load_postgres_config(testing=True)` (`app/database/database.py:70`), que lê
**`TEST_DATABASE_URL`** (`app/database/config.py:90`). `DATABASE_URL` é usada apenas como
referência de comparação, para recusar um teste apontado ao banco operacional.

Consequência prática: subir a instância de homologação exige sobrescrever `TEST_DATABASE_URL`.
A primeira tentativa desta execução sobrescreveu `DATABASE_URL` e a instância subiu, respondeu
`schema_version: 15` e serviu dados — porém do banco `gestor_pecas_test_simulacao_residencia_20260824`.
Esse banco possui tempo padrão descalibrado e exibia OEE de até **232,3%**, o que produziu um falso
alarme de divergência industrial. Corrigido; a guarda `GESTOR_EXPECTED_DATABASE` foi adicionada ao
launcher para impedir a repetição do erro.

**Recomendação:** documentar `TEST_DATABASE_URL` como a variável operante no `README.md`, que hoje
menciona apenas `DATABASE_URL` na seção de configuração.

---

## 2. Arquitetura final — [CONFIRMADO]

```
React / TypeScript (web/)
        ↓ HTTP + SSE
FastAPI (backend/api/)  — 52 rotas sob /api/v1
        ↓
serviços / contratos (mes/services, mes/contracts)
        ↓
domínio / analytics (mes/domain, mes/analytics)
        ↓
PostgreSQL (app/database) — schema 15
```

Distribuição das 52 rotas:

| Prefixo | Rotas | Prefixo | Rotas |
|---|---|---|---|
| `/api/v1/reports` | 9 | `/api/v1/orders` | 3 |
| `/api/v1/operator` | 8 | `/api/v1/system` | 3 |
| `/api/v1/management` | 5 | `/api/v1/analytics` | 2 |
| `/api/v1/operations` | 5 | `/api/v1/cutting` | 2 |
| `/api/v1/ai` | 4 | `/api/v1/highlight` | 2 |
| `/api/v1/audit` | 3 | `/api/v1/traceability` | 2 |
| `/api/v1/auth` | 3 | `/api/v1/andon` | 1 |

Política declarada em `/api/v1/system/capabilities`: `calculation_policy: backend_only`,
`frontend_must_recalculate_metrics: false`, `active_data_source: postgresql_test_only`.

---

## 3. Schema 15 — [CONFIRMADO]

Migration 14 → 15 executada em banco descartável (`gestor_pecas_test_migracao_15_tmp`, removido ao final).

- `apply_migrations` retornou **15**; versão anterior **14**.
- Tabelas criadas: `generated_reports`, `messaging_destinations`, `report_schedules`, `report_deliveries`.
- Tabelas removidas: **nenhuma**. Tabelas antes: 33 → depois: 37.
- **Idempotência:** segunda execução retornou 15, `schema_migrations` permaneceu com 15 linhas, 37 tabelas.
- **Composição da migration:** 4 `CREATE TABLE` + 4 `CREATE INDEX`. Zero `ALTER TABLE`, `INSERT`,
  `UPDATE`, `DELETE` ou `DROP` — portanto **sem backfill produtivo** e **sem alteração de tabelas industriais**.

### 3.1 Integridade referencial

| Tabela | FK | Ação |
|---|---|---|
| `generated_reports` | `created_by → usuarios(id)` | CASCADE |
| `messaging_destinations` | `user_id → usuarios(id)` | CASCADE |
| `report_schedules` | `created_by → usuarios(id)` | CASCADE |
| `report_schedules` | `destination_id → messaging_destinations(id)` | SET NULL |
| `report_deliveries` | `report_id → generated_reports(id)` | CASCADE |
| `report_deliveries` | `requested_by → usuarios(id)` | CASCADE |
| `report_deliveries` | `destination_id → messaging_destinations(id)` | **RESTRICT** |

O `RESTRICT` em `report_deliveries.destination_id` preserva o histórico de entrega contra remoção
silenciosa de destino — decisão correta para rastreabilidade.

### 3.2 Constraints e índices relevantes

- `uq_generated_reports_idempotency UNIQUE (created_by, idempotency_key)`
- `ck_generated_reports_period CHECK (period_end > period_start)`
- `generated_reports_status_check` — `gerando | pronto | falhou | expirado`
- `generated_reports_source_check` — `chat | manual | automatico`
- `uq_messaging_destination UNIQUE (user_id, provider, destination_ref)`
- `messaging_destinations_provider_check CHECK (provider = 'telegram')`
- `report_deliveries_attempt_check CHECK (attempt BETWEEN 1 AND 10)`
- `report_deliveries_idempotency_key_key UNIQUE (idempotency_key)`
- `report_schedules_frequency_check` — `diario | semanal | mensal`
- Índices parciais: `idx_generated_reports_expiration WHERE expires_at IS NOT NULL`,
  `idx_report_schedules_due WHERE enabled IS TRUE`

---

## 4. OEE canônico — [CONFIRMADO]

Fórmula em `mes/analytics/oee.py`, **não alterada** nesta execução:

```
availability = worked_seconds / available_seconds
performance  = productive_net_seconds / worked_seconds
ftt          = good / (good + scrap + rework)
oee          = availability × performance × ftt
```

`productive_net_seconds = standard_run_seconds + supporting_productive_seconds`, onde
`standard_run_seconds = tempo_medio_segundos × quantidade_boa`.

**Verificação de canonicidade em três camadas** para o mesmo período (01/08/2026 00:00 a 24/08/2026 08:32):

| Camada | OEE |
|---|---|
| Backend (`FrontendBackendFacade.inicio`) | `89.6683920000%` |
| Workbook XLSX, aba `OEE`, célula C5 | `89.66839199998785` |
| Workbook XLSX, aba `Resumo Executivo`, A7 | `0.8966839199998785` (formato `0.0%`) |

Coincidência até a 10ª casa decimal. O Excel não recalcula: **zero fórmulas** no workbook inteiro.

No Andon (período 24/08 00:00–08:32), 10 dos 24 recursos possuem OEE apurado, faixa **50,70% a 92,57%**,
**nenhum acima de 100%**.

Observação: a fórmula é intencionalmente não limitada a 100%. Performance acima de 100% é sinal
industrial legítimo de tempo padrão desatualizado, não erro de cálculo. Isso foi comprovado ao
reproduzir manualmente, a partir do SQL bruto, o valor de 233,33% do banco de residência.

---

## 5. IA e tools — [CONFIRMADO] (matriz automatizada) / [NÃO VERIFICADO] (amostra real)

- `GESTOR_AI_ENABLED=true`, `GROQ_API_KEY` presente, `ai_configured=True`.
- Modelo padrão: `openai/gpt-oss-120b`; `reasoning_effort=medium`; `temperature=0.2`;
  `max_completion_tokens=640`; `max_tool_rounds=6`; `request_token_budget=6000`; `timeout=60s`.
- **15 tools** em `TOOL_REGISTRY`, agrupadas em 11 grupos:

`explain_kpi`, `generate_industrial_report`, `get_audit_issues`, `get_downtimes`,
`get_factory_status`, `get_management_insights`, `get_management_overview`, `get_nestings`,
`get_production`, `get_production_orders`, `get_quality`, `get_resource_status`,
`get_sector_status`, `get_setups` (+ fallback).

Garantias cobertas por teste automatizado:

- `test_matriz_disponibiliza_tool_canonica_e_retorna_fato_sem_recalculo` — a tool devolve fato canônico sem recálculo;
- `test_solicitacoes_de_segredo_escrita_sql_e_injecao_nao_recebem_tools` — pedidos de segredo, SQL e injeção não recebem tools;
- `test_whitelist_nao_possui_escrita_produtiva` — nenhuma tool escreve produção;
- `test_backend_nega_todas_as_tools_sem_acesso_gerencial` — sem acesso gerencial, nenhuma tool.

### 5.1 Amostra real Groq — [NÃO VERIFICADO]

`GESTOR_AI_REAL_TEST` está **ausente** do ambiente. Conforme instrução explícita ("Não alterar essa
flag automaticamente se estiver false"), a flag não foi habilitada e **nenhuma chamada real à Groq
foi executada**. As cinco perguntas previstas ("Como está a fábrica?", "Qual é o OEE da fábrica?",
"O que precisa da minha atenção?", "Quanto foi produzido?", "Quais OPs estão em andamento?")
permanecem sem execução real, e portanto sem registro de `prompt_tokens`, `completion_tokens`,
`total_tokens` e `finish_reason`.

---

## 6. ReportService e artifacts — [CONFIRMADO]

Tipos: `completo`, `gerencial`, `producao`, `ops`, `paradas`, `setup`, `qualidade`, `indicadores`, `recursos`.
Períodos: `hoje`, `ontem`, `esta_semana`, `semana_anterior`, `este_mes`, `mes_anterior`, `personalizado`.

Configuração: `report_expiration_hours=168`, `report_max_bytes=50MB`,
`report_artifact_dir=dados/relatorios_gerados`.

O payload do artifact **não expõe** `storage_path`. `telegram_available` e `telegram_destination_id`
só existem no payload quando há messaging configurado e destino do próprio usuário.

### 6.1 Validação do workbook mensal

Arquivo: `gestor_completo_2026-08-01_2edc34d1.xlsx`, 601.332 bytes, período 01/08 00:00 a 24/08 08:32.

| Verificação | Resultado |
|---|---|
| Container OOXML íntegro | sim (42 entradas, `testzip` limpo) |
| Abas | **12**, exatamente as esperadas |
| Células preenchidas | 71.545 |
| Fórmulas no workbook | **0** |
| Células com prefixo de injeção (`=`, `+`, `-`, `@`) | **0** |
| Abas vazias | nenhuma |
| Congelamento de cabeçalho | `A5` em todas as 12 abas |
| Larguras de coluna definidas | todas as colunas de todas as abas |
| Datas | tipo `datetime` real, formato `dd/mm/yyyy hh:mm:ss` |
| Percentuais | razão + formato `0.0%` (sem escala dupla) |
| Acentuação UTF-8 | preservada (`PEÇAS`, `RELATÓRIO`, `Produção`, `Exceções`) |
| Dados calculados fora do backend | nenhum (ver §4) |

Abas: `Resumo Executivo`, `OEE`, `Produção`, `OPs`, `Paradas`, `Setup`, `Qualidade`, `Recursos`,
`Setores`, `Nestings`, `Exceções`, `Auditoria`.

### 6.2 Prévias de renderização — [NÃO VERIFICADO]

`tools/verify_report_artifact.mjs` importa `@oai/artifact-tool`. Esse pacote **não existe** na árvore
de dependências deste projeto — não há `package.json` na raiz e ele não está em `web/node_modules`.

Reprodução do código 1 nesta execução:

```
Error [ERR_MODULE_NOT_FOUND]: Cannot find package '@oai/artifact-tool'
    imported from tools/verify_report_artifact.mjs
EXIT=1
```

A causa do código 1 **nesta máquina** está explicada e é diferente da causa original: aqui o script
nem chega a executar, enquanto a execução anterior produziu as 12 imagens antes de encerrar em 1.
Sem o pacote, a causa original **não é reproduzível** e permanece não explicada.

As 12 imagens de `outputs/evolucao_inteligencia_2026-08-26/previews/` foram inspecionadas
individualmente e estão corretas — `resumo_executivo.png` exibe OEE 89.7% / Disponibilidade 92.6% /
Performance 97.6% / FTT 99.3%, coerentes com o backend, com acentuação e período corretos.

---

## 7. Scheduler — [CONFIRMADO]

Períodos fechados (`closed_report_period`), verificados para referência 26/08/2026 09:00:

| Frequência | Janela |
|---|---|
| diário | 25/08 00:00 → 26/08 00:00 |
| semanal | 17/08 00:00 → 24/08 00:00 |
| mensal | 01/07 00:00 → 01/08 00:00 |

Comportamento homologado por teste automatizado:

- **diário, semanal e mensal**: cada frequência produz **exatamente um** artifact e **uma** chamada ao provider;
- **ciclo repetido**: mesmo `artifact.id`, `generated_reports` permanece com 1 registro, provider não é chamado de novo;
- **reinício de processo**: nova instância de `ReportScheduler` não regenera nem reenvia; entrega única com `attempt=1`;
- **falha de envio**: artifact preservado, delivery marcado `falhou`, retry reaproveita a mesma entrega;
- **automação desabilitada por padrão**: `report_automation_enabled`, `telegram_enabled` e `ai_enabled`
  são `False` no default de `WebSettings.from_env`.

---

## 8. Telegram — [CONFIRMADO] (provider fake) / [NÃO VERIFICADO] (envio real)

Fluxo homologado ponta a ponta em HTTP com provider fake:

```
request do frontend → autenticação → autorização gerencial → artifact existente
→ destino autorizado → ReportMessagingService → TelegramProvider fake → delivery registrado
```

Cenários cobertos pelo teste `test_envio_telegram_http_homologa_permissao_posse_falha_e_idempotencia`:

| Cenário | Resultado |
|---|---|
| Telegram desabilitado | 409 `messaging_disabled`, provider não chamado, nenhum delivery |
| Operador (sem acesso gerencial) | 403 |
| Artifact de outro usuário | 404 `report_not_found` |
| Artifact inexistente | 404 `report_not_found` |
| Destino de outro usuário | 404 `messaging_destination_not_found` |
| Sem CSRF | 403 |
| Provider falhando | 502 `messaging_provider_error`, delivery `falhou` com `attempt=1` |
| Relatório após falha | continua disponível para download (200, assinatura `PK`) |
| Retry após falha | 200 `enviado`, `attempt=2`, mesma entrega |
| Reenvio após sucesso | 200, mesmo `delivery.id`, `attempt` não avança, provider não é chamado |
| Duplicação | 1 artifact, 1 delivery, 2 chamadas ao provider (falha + retry) |
| Vazamento de destino | `destination_ref` nunca aparece na resposta |

### 8.1 Envio real — [NÃO VERIFICADO]

`TELEGRAM_ENABLED` e `TELEGRAM_BOT_TOKEN` estão **ausentes** do ambiente. Nenhum envio real foi
executado. Nenhum token foi solicitado ou impresso. A arquitetura é considerada homologada com
provider fake, conforme previsto no critério de encerramento.

---

## 9. Permissões — [CONFIRMADO]

- Autenticação por cookie HTTP-only + CSRF em toda escrita.
- `require_management_user` protege área gerencial, relatórios e IA.
- `require_andon_user` protege o Andon; o perfil `andon` acessa somente o Andon.
- Operador é restrito ao próprio setor e aos próprios recursos; a sessão expõe apenas isso.
- Eventos produtivos históricos não possuem API genérica de edição ou exclusão.

---

## 10. Testes

### 10.1 Suíte Python — [CONFIRMADO]

| Métrica | Valor |
|---|---|
| Executados | **278** |
| Aprovados | **278** |
| Falhas | **0** |
| Skips | **0** |
| Duração | 49,7s |

Banco de integração: `TEST_DATABASE_URL` do `.env` (`gestor_pecas_test_simulacao_residencia_20260824`),
mantido isolado do banco de homologação para que a suíte não altere os dados sob validação.

**Correção aplicada:** `tests/test_web_api.py` esperava a aba `"Resumo"`; o nome canônico é
`"Resumo Executivo"`, comprovado por `mes/services/industrial_reports.py:31` e por
`tests/test_intelligence_reports.py:124`. Expectativa obsoleta do renome, não regressão de produto.

**Testes adicionados nesta execução:**
- `test_envio_telegram_http_homologa_permissao_posse_falha_e_idempotencia` (item 4);
- `test_cada_frequencia_gera_exatamente_um_artifact_e_o_ciclo_repetido_nao_duplica` (item 10);
- `test_automacao_permanece_desabilitada_por_padrao` (item 10).

### 10.2 Suíte Web — [CONFIRMADO]

| Métrica | Valor |
|---|---|
| Arquivos | 5 |
| Testes | **36** |
| Aprovados | **36** |
| Execuções consecutivas verdes | 3 |

Cobertura verificada dos pontos exigidos: IA, artifacts, download (`Baixar Excel`), ações rápidas,
botão Telegram, **botão oculto quando Telegram indisponível** (adicionado), Markdown (incluindo
recusa de HTML arbitrário), streaming, streaming progressivo, cooldown, `Enter`, `Shift+Enter`,
retry e cancelamento.

**Flake corrigido:** `findByRole("link", {name:"Baixar Excel"})` usava o timeout padrão de 1000ms.
Isolado passava 3/3; na suíte completa falhava intermitentemente (1 falha em 2 execuções) por
contenção entre os 5 arquivos em paralelo. Foi adicionado `{ timeout: 5000 }` às duas asserções.
Nenhuma expectativa foi alterada — apenas o orçamento de espera. Após a correção: 3 execuções
completas verdes.

### 10.3 Build — [CONFIRMADO]

`npm run build` — **exit 0**, concluído em 5,86s.

- **Errors: 0**
- **Warnings: 1** — `Some chunks are larger than 500 kB after minification`
  (`index-dNgj5jPl.js`, 591,91 kB / 195,36 kB gzip). Aviso informativo do Vite sobre chunking,
  não impede o build nem a execução.

---

## 11. Reconciliação e performance

### 11.1 Reconciliação SQL → serviços → API — [CONFIRMADO com ressalva]

Reexecutada contra o banco de homologação. Resultado idêntico ao anterior:

| Total | Aprovados | Falhas | Gate |
|---|---|---|---|
| 204 | 202 | 2 | FAIL |

As 2 falhas são **exclusivamente de performance**. **Nenhuma divergência de valor, regra, unidade ou
escopo foi encontrada** — os 202 checks de consistência industrial passam integralmente.

### 11.2 Medições repetidas — [CONFIRMADO]

7 repetições por endpoint, HTTP real contra a instância 8001, período 01/06/2026 06:00 a 24/08/2026 08:32:

| Endpoint | Limite | min | **mediana** | max | Veredito |
|---|---|---|---|---|---|
| `/api/v1/analytics/oee` | 5.000 ms | 5.351,2 | **5.514,8** | 5.920,0 | **acima do limite** |
| `/api/v1/reports/indicadores` | 8.000 ms | 7.712,6 | **7.804,4** | 8.047,6 | mediana abaixo |

`/reports/indicadores`: mediana **abaixo** do limite → a falha anterior (8.886,7 ms) classifica-se como
**variação do ambiente de homologação**. Margem estreita: 2,4%.

`/analytics/oee`: mediana **acima** do limite, com dispersão de apenas 570 ms entre min e max.
Não é variação de ambiente — é custo estrutural.

### 11.3 Gargalo do `/analytics/oee` — [CONFIRMADO]

Perfilamento em processo, mesmo período:

| Etapa | Tempo | Participação |
|---|---|---|
| `get_overview` (frio) | 2.593 ms | 46,9% |
| `get_oee_evolution` | **3.532 ms** | **63,9%** |
| `facade.inicio` (segunda chamada) | **0 ms** | cache efetivo |
| **Rota total** | **5.529 ms** | (mediana HTTP: 5.514,8 ms) |

**Causa:** `ManagementService.get_oee_evolution` (`mes/services/management.py:448`) divide o período em
até `_MAX_OEE_EVOLUTION_POINTS = 31` intervalos e chama `get_overview` **uma vez por intervalo**.
Para 85 dias: `bucket_days = 3`, **29 execuções** de `get_overview` a 122 ms cada.

Classificação: **N+1**. A rota não possui query redundante — o `_overview_cache` funciona e a segunda
chamada (`facade.inicio`) custa 0 ms.

**Não corrigido, deliberadamente.** O docstring do método declara que o desenho existe justamente para
que a série temporal nunca replique a fórmula de OEE, reusando o caminho canônico por intervalo. É
uma troca consciente de desempenho por correção. Qualquer otimização real exigiria uma agregação SQL
única por bucket — reescrita substancial, com risco de alterar valores de OEE — ou cache de dado
industrial. Ambos foram vetados pelo escopo desta execução.

**Recomendações, em ordem de risco crescente:**
1. Reduzir `_MAX_OEE_EVOLUTION_POINTS` (menos pontos no gráfico, menos buckets) — decisão de produto;
2. Paralelizar os buckets no pool PostgreSQL (`max_pool_size` atual: 4);
3. Reescrever a série como agregação SQL única com `GROUP BY` por bucket, validada contra o caminho atual.

---

## 12. Segurança — [CONFIRMADO]

Regressões cobertas por teste automatizado:

| Vetor | Cobertura |
|---|---|
| IDOR de relatório | `test_relatorio_gerado_tem_download_autorizado_e_idor_negado` + teste HTTP do item 4 |
| Artifact de outro usuário | teste HTTP do item 4 (404) |
| Messaging destination de outro usuário | teste HTTP do item 4 + `test_destino_de_outro_usuario_e_ocultado` |
| Path traversal | `test_reports_postgres.py` (`'../escape.xlsx'`) |
| Excel formula injection | `test_workbook_completo_preserva_kpi_oficial_utf8_e_formula_injection` + varredura de 71.545 células (0 ocorrências) |
| XSS | `ai.test.tsx` — Markdown renderizado, HTML arbitrário ignorado |
| CSRF | exigido em login, logout, generate, send |
| Acesso sem autenticação | 401 em rotas protegidas |
| Escalada de setor | `test_operador_nao_pode_consultar_ou_apontar_recurso_de_outro_setor` |
| SQL solicitado via IA | `test_solicitacoes_de_segredo_escrita_sql_e_injecao_nao_recebem_tools` |
| Escrita produtiva via IA | `test_whitelist_nao_possui_escrita_produtiva` |
| Leitura de secrets | `test_variaveis_sao_validadas_e_a_chave_nao_aparece_no_repr`, `test_health_nao_expoe_dsn` |

### 12.1 Varredura de vazamento de segredos

`GROQ_API_KEY` e `POSTGRES_PASSWORD` foram procurados literalmente em 10 superfícies:

| Superfície | Resultado |
|---|---|
| `web/dist/index.html` | limpo |
| `web/dist/assets/*.css` | limpo |
| `web/dist/assets/*.js` (bundle) | limpo |
| `/api/v1/system/health` | limpo |
| `/api/v1/system/capabilities` | limpo |
| `/api/openapi.json` | limpo |
| `/api/v1/openapi.json` | limpo |
| Artifact XLSX (conteúdo descompactado) | limpo |
| `dados/app_erros.log` | limpo |
| `repr(WebSettings)` | limpo |

**Nenhum segredo exposto em nenhuma superfície**, com `ai_configured=True` e chave efetivamente carregada.

---

## 13. Andons — homologação visual [CONFIRMADO com ressalva]

Autenticação real: perfil `admin` (`management_access` e `andon_access`), sessão de navegador.

### 13.1 Andon TV — rota `/andon`

| Viewport | `document.scrollWidth` | viewport width | `document.scrollHeight` | Recursos | Modo | Sidebar |
|---|---|---|---|---|---|---|
| 1920×1080 | 1920 | 1920 | 1080 | **24** | `single-view` | ausente |
| 1600×900 | 1585 | 1600 | 2223 | **24** | padrão | ausente |
| 1366×768 | 1351 | 1366 | 2223 | **24** | padrão | ausente |

### 13.2 Andon gerencial — rota `/inicio/andon`

| Viewport | `document.scrollWidth` | viewport width | `document.scrollHeight` | Recursos | Modo | Sidebar |
|---|---|---|---|---|---|---|
| 1920×1080 | 1905 | 1920 | 2352 | **24** | `embedded` | 327px |
| 1600×900 | 1585 | 1600 | 2582 | **24** | `embedded` | 272px |
| 1366×768 | 1351 | 1366 | 3462 | **24** | `embedded` | 233px |

### 13.3 Verificações objetivas — todos os 6 cenários

| Critério | Resultado |
|---|---|
| Overflow horizontal indevido | **nenhum** (`scrollWidth ≤ viewport` em todos) |
| Elementos fora do viewport | **0** |
| Cards cortados | **nenhum** |
| Elementos sobrepostos | **0** |
| Setores visíveis | **6** — CORTE, DOBRA, USINAGEM, SERRA, PINTURA, SOLDA |
| Recursos visíveis | **24** em todos os cenários |
| Estados | categorias canônicas de `eventos_estado_recurso` |
| OEE consistente | 10 recursos com valor, faixa 50,70%–92,57%, **0 acima de 100%** |
| Sidebar apenas onde deve existir | TV sem sidebar; gerencial com sidebar |
| Andon TV passivo | `single-view`, sem navegação, sem `<nav>` |
| Andon gerencial integrado | `andon-page--embedded` dentro do `app-shell` com abas |
| Densidade visual preservada | `single-view` mantém 24 cards em uma tela sem rolagem |

### 13.4 Ressalva — não corrigida por não ser defeito

Em 1920×1080 (`single-view`), dois elementos com o rótulo `PRODUZIDO / PREVISTO` a 7px têm
`scrollWidth` 42 contra `clientWidth` 40 — transbordo de 2px da própria caixa. A verificação de
ancestrais retornou `clipadoPor: null`: **nenhum ancestral recorta o texto**, que permanece
integralmente visível. Não é corte nem ilegibilidade; nenhuma correção aplicada.

As fontes de 6–9px do `single-view` são deliberadas, definidas em
`@media (min-width: 1700px) and (min-height: 900px)` em `web/src/styles/global.css:603`, para caber
24 recursos em uma tela sem rolagem. Fora dessa media query o Andon usa a escala normal (mínimo 9px).

### 13.5 Limitação de evidência — [NÃO VERIFICADO]

O painel do navegador compõe o viewport emulado de 1920×1080 em aproximadamente 240×135px da
captura — redução de cerca de 8×. **Não foi possível produzir evidência em pixels** para julgar
tipografia, contraste ou espaçamento fino. Toda a homologação visual acima é baseada em geometria de
DOM, que é objetiva e cobre exatamente os critérios exigidos, mas não substitui inspeção visual
humana em tela real.

---

## 14. UX de geração de relatório — [CONFIRMADO com ressalva]

Relatório `completo`, período `este_mes` (01/08 00:00 a 24/08 08:32), disparado do navegador
autenticado contra a instância 8001.

| Métrica | Valor |
|---|---|
| **Tempo real medido** | **38.151 ms** (38,2s) |
| Status | 201 |
| Artifact | `gestor_completo_2026-08-01_2edc34d1.xlsx`, 601.332 bytes, `status: pronto` |
| `storage_path` no payload | ausente (correto) |
| Download | 200, assinatura `PK` |

Responsividade durante a geração:

| Métrica | Valor |
|---|---|
| `/api/v1/andon` durante a geração | **200 em 215 ms** (`aindaGerando: true`) |
| Mediana do intervalo entre frames | **17 ms** (~60fps) |
| Maior intervalo entre frames | 96 ms |
| Frames medidos | 2.286 |

**Frontend não congela e a aplicação permanece responsiva.** A geração roda em
`asyncio.to_thread`, sem bloquear o event loop.

O tempo real é **38,2s**, quase o dobro dos ~20s registrados anteriormente. Como a experiência
assíncrona está correta e o gargalo do relatório é o mesmo custo agregado já analisado em §11.3,
**não foi feita otimização prematura**, conforme instruído.

### 14.1 Defeito — duplicação por cliques simultâneos

Dois `POST /api/v1/reports/generate` idênticos e simultâneos produziram **dois artifacts distintos**:

```
2edc34d1-f5e5-4613-bafd-7b9bd67bd749  gestor_completo_2026-08-01_2edc34d1.xlsx  601.332 bytes
c233af75-4a08-4e51-ac0d-a3c0aceb1195  gestor_completo_2026-08-01_c233af75.xlsx  601.334 bytes
```

Ambos gravados em disco em `dados/relatorios_gerados/2026/08/24/`. A constraint
`uq_generated_reports_idempotency (created_by, idempotency_key)` existe, mas a geração manual não
deriva uma `idempotency_key` estável a partir de tipo + período + filtros — ao contrário do
scheduler, que é comprovadamente idempotente (§7).

Os itens de UX "múltiplos cliques não criam relatórios duplicados" e "artifact aparece quando
concluído / botão de download funciona / falha apresenta mensagem amigável" no **card do chat da IA**
dependem do fluxo com Groq real e permanecem cobertos apenas pela suíte Vitest com stream mockado —
ver §5.1.

---

## 15. Porta 8000 — [CONFIRMADO]

| Item | Valor |
|---|---|
| PID | **19524** |
| Processo | `python.exe` |
| Início | 26/08/2026 09:17:08 |
| CommandLine / Path | inacessíveis via WMI e `Get-Process` |
| Uso nesta homologação | **nenhum** |

Processo legado preso, sem linha de comando recuperável. Conforme instrução, não foi despendido
esforço em gerenciamento de processos do Windows. **Nenhuma validação desta execução tocou a porta
8000**; todas apontaram explicitamente para `127.0.0.1:8001` (PID 25528).

---

## 16. Defeitos abertos

| # | Defeito | Severidade | Local |
|---|---|---|---|
| **D1** | Filtro padrão usa relógio do navegador. Em modo simulação `Hoje` e `Ontem e hoje` retornam 400 `invalid_period`, e qualquer refresh ou deep link abre a tela gerencial em erro. | **Alta no ambiente de homologação**; nula em produção sem simulação | `web/src/filters/FilterContext.tsx:29` vs `backend/api/dependencies/filters.py:30` |
| **D2** | Geração manual de relatório duplica artifact e arquivo em cliques simultâneos. | Média | `backend/api/routers/reports.py:44` — falta `idempotency_key` derivada |
| **D3** | `/api/v1/analytics/oee` com mediana 5.514,8 ms contra limite de 5.000 ms, por N+1 de 29 `get_overview`. | Média | `mes/services/management.py:448` |
| **D4** | `tools/verify_report_artifact.mjs` depende de `@oai/artifact-tool`, ausente do projeto. Prévias não reproduzíveis; causa original do código 1 não explicada. | Baixa | `tools/verify_report_artifact.mjs:3` |
| **D5** | Workbook não aplica `auto_filter` em nenhuma aba, embora "filtros" conste do checklist de homologação. | Baixa | `backend/api/report_workbook.py` |
| **D6** | Aba `OEE` tem duas colunas chamadas `Valor` e cabeçalhos em inglês (`At`, `Period Start`, `Period End`, `Components`) em relatório português. | Baixa (cosmética) | `backend/api/report_workbook.py` |

Correção recomendada para **D1**: alimentar `defaults()` com `simulation.reference_time` de
`/api/v1/system/capabilities` quando a simulação estiver ativa. Não aplicada por alterar o contrato
de qual camada é dona do "hoje" — decisão de produto, fora do escopo de homologação.

---

## 17. Pendências e limitações

### [NÃO VERIFICADO]
- Amostra real da IA com Groq — `GESTOR_AI_REAL_TEST` ausente (§5.1);
- Envio real de Telegram — `TELEGRAM_ENABLED` e token ausentes (§8.1);
- Evidência visual em pixels dos Andons — painel do navegador reduz a captura em ~8× (§13.5);
- Causa original do código 1 nas prévias — dependência indisponível (§6.2);
- UX do card "Gerando relatório…" no chat da IA em navegador real — depende de Groq (§14.1).

### [A DEFINIR]
- Contrato de integração corporativa TOTVS/Protheus — `CorporatePlanningGateway` permanece desacoplado;
- Mapeamento de banco corporativo (`pending_official_definition.corporate_database_mapping: true`);
- Estratégia de rateio por cenário (`rateio_strategy_by_scenario: true`);
- Tratamento oficial de OEE/FTT com refugo e retrabalho (`oee_ftt_with_scrap_rework: false`);
- Se `auto_filter` deve integrar o padrão do workbook (D5);
- Se `_MAX_OEE_EVOLUTION_POINTS` pode ser reduzido para trazer `/analytics/oee` ao limite (D3).

### Limitações estruturais conhecidas
- `web/node_modules` contém 507 junctions quebrados apontando para o perfil `logistica.unidade4`,
  vindos de instalação `pnpm` em outra máquina. As dependências de topo funcionam; `pnpm install`
  reconstruiria os links.
- Qlik é legado bloqueado e não recebe novas regras de negócio.
- O `.env` do projeto não define `GESTOR_WEB_SESSION_SECRET`; sem ele o backend gera segredo efêmero
  e toda sessão cai a cada reinício. Em produção `WebSettings.from_env` recusa subir sem a variável.

---

## 18. Ambiente de execução

| Componente | Versão |
|---|---|
| Python | 3.14.7 |
| FastAPI | 0.141.1 |
| Uvicorn | 0.52.4 |
| Node.js | 24.19.0 |
| npm | 11.17.0 |
| Vitest | 3.2.7 |
| PostgreSQL | `127.0.0.1:15432` |
| SO | Windows 11 Pro 10.0.26200 |

---

**Autor do sistema:** Iago Luchtenberg da Silva

---

## 19. Matriz final de aceitação

| Área | Teste | Resultado | Evidência | Status |
|---|---|---|---|---|
| OEE | Canonicidade em 3 camadas (backend / aba OEE / Resumo Executivo) | `89.6683920000%` idêntico até a 10ª casa | §4 | **APROVADO** |
| OEE | Nenhum recurso acima de 100% no Andon | 10 com valor, faixa 50,70%–92,57%, 0 acima | §4, §13.3 | **APROVADO** |
| OEE | Fórmula não alterada | `mes/analytics/oee.py` intocado | §4 | **APROVADO** |
| Andon TV | 1920×1080 / 1600×900 / 1366×768 | 24 recursos, 6 setores, 0 overflow, 0 sobreposição, sem sidebar | §13.1, §13.3 | **APROVADO** |
| Andon TV | Permanece passivo | `single-view`, sem `<nav>`, sem navegação | §13.3 | **APROVADO** |
| Andon gerencial | 1920×1080 / 1600×900 / 1366×768 | 24 recursos, 6 setores, 0 overflow, sidebar 327/272/233px | §13.2, §13.3 | **APROVADO** |
| Andon gerencial | Integrado à interface | `andon-page--embedded` no `app-shell` | §13.3 | **APROVADO** |
| Andon | Evidência visual em pixels | painel reduz captura em ~8× | §13.5 | **NÃO VERIFICADO** |
| IA | Matriz automatizada de tools e intenções | 15 tools, fato canônico sem recálculo | §5 | **APROVADO** |
| IA | Amostra real com Groq (5 perguntas) | `GESTOR_AI_REAL_TEST` ausente; flag não alterada | §5.1 | **NÃO VERIFICADO** |
| Segurança IA | Segredo, SQL e injeção não recebem tools | `test_solicitacoes_de_segredo_escrita_sql_e_injecao_nao_recebem_tools` | §12 | **APROVADO** |
| Segurança IA | Nenhuma escrita produtiva na whitelist | `test_whitelist_nao_possui_escrita_produtiva` | §12 | **APROVADO** |
| Excel | 12 abas, 0 fórmulas, 0 injeção, 0 abas vazias | 71.545 células varridas | §6.1 | **APROVADO** |
| Excel | Freeze A5, larguras, datas, percentuais, UTF-8 | todas as 12 abas | §6.1 | **APROVADO** |
| Excel | `auto_filter` nas abas | ausente em todas | D5, §16 | **APROVADO COM RESSALVA** |
| Excel | Cabeçalhos da aba OEE | duas colunas `Valor`, rótulos em inglês | D6, §16 | **APROVADO COM RESSALVA** |
| Excel | Prévias de renderização | 12 PNGs corretos; gerador não reproduzível | §6.2, D4 | **NÃO VERIFICADO** |
| Download | Autorizado, IDOR negado, sem `storage_path` | 200 `PK`; 404 para outro usuário | §6, §8, §12 | **APROVADO** |
| Scheduler diário | Exatamente um artifact; ciclo repetido não duplica | `test_cada_frequencia_...` | §7 | **APROVADO** |
| Scheduler semanal | Exatamente um artifact; ciclo repetido não duplica | `test_cada_frequencia_...` | §7 | **APROVADO** |
| Scheduler mensal | Exatamente um artifact; ciclo repetido não duplica | `test_cada_frequencia_...` | §7 | **APROVADO** |
| Scheduler | Reinício não reenvia após sucesso | `attempt=1`, provider não rechamado | §7 | **APROVADO** |
| Scheduler | Falha preserva artifact + retry controlado | delivery `falhou`, mesma entrega no retry | §7 | **APROVADO** |
| Scheduler | Automação desabilitada por padrão | `report_automation_enabled=False` | §7 | **APROVADO** |
| Telegram fake | Fluxo ponta a ponta HTTP, 12 cenários | `test_envio_telegram_http_homologa_...` | §8 | **APROVADO** |
| Telegram fake | Sem duplicação; relatório sobrevive à falha | 1 artifact, 1 delivery, download 200 após 502 | §8 | **APROVADO** |
| Telegram real | Envio real | `TELEGRAM_ENABLED` e token ausentes | §8.1 | **NÃO VERIFICADO** |
| Migration 15 | 14 → 15 em banco descartável | retorno 15; 4 tabelas criadas, 0 removidas | §3 | **APROVADO** |
| Migration 15 | Idempotência do migrador | 2ª execução sem alteração | §3 | **APROVADO** |
| Migration 15 | Constraints, índices, FKs, cascades | 7 FKs com CASCADE/SET NULL/RESTRICT corretos | §3.1, §3.2 | **APROVADO** |
| Migration 15 | Sem backfill e sem alterar tabela industrial | 4 CREATE TABLE + 4 CREATE INDEX, zero DML | §3 | **APROVADO** |
| Frontend | Suíte Vitest integral | 36/36, 3 execuções verdes | §10.2 | **APROVADO** |
| Frontend | Botão Telegram oculto quando indisponível | teste adicionado | §10.2 | **APROVADO** |
| Frontend | Filtro padrão em modo simulação | `Hoje` e refresh → 400 `invalid_period` | D1, §16 | **REPROVADO** |
| Backend | Suíte Python integral | 278/278, 0 falhas, 0 skips | §10.1 | **APROVADO** |
| Backend | Duplicação de relatório manual | 2 POSTs simultâneos → 2 artifacts | D2, §14.1 | **REPROVADO** |
| PostgreSQL | Health e schema | `status: ok`, `schema_version: 15` | §1 | **APROVADO** |
| PostgreSQL | Reconciliação SQL → serviços → API | 202/204; nenhuma divergência de valor, regra, unidade ou escopo | §11.1 | **APROVADO** |
| Performance | `/reports/indicadores` | mediana 7.804,4 ms < 8.000 ms | §11.2 | **APROVADO COM RESSALVA** |
| Performance | `/analytics/oee` | mediana 5.514,8 ms > 5.000 ms; N+1 de 29 buckets | §11.2, §11.3, D3 | **REPROVADO** |
| Performance | UX assíncrona da geração | app responsivo (200 em 215 ms), 60fps, 38,2s | §14 | **APROVADO** |
| Segurança de arquivos | Path traversal | `test_reports_postgres.py` (`'../escape.xlsx'`) | §12 | **APROVADO** |
| Segurança de arquivos | Vazamento de segredos | 10 superfícies varridas, todas limpas | §12.1 | **APROVADO** |
| Build | `npm run build` | exit 0, 0 errors, 1 warning (chunk >500 kB) | §10.3 | **APROVADO** |
| Porta 8000 | Não utilizada | PID 19524 documentado; 100% das validações em 8001 | §15 | **APROVADO** |

### 19.1 Consolidado

| Status | Quantidade |
|---|---|
| APROVADO | 35 |
| APROVADO COM RESSALVA | 3 |
| REPROVADO | **3** |
| NÃO VERIFICADO | 4 |
| A DEFINIR | 0 |

---

## 20. Critério de encerramento

| Condição | Situação |
|---|---|
| Suíte Python integral passar | **cumprido** — 278/278 |
| Suíte Web integral passar | **cumprido** — 36/36, 3 execuções |
| Build final passar | **cumprido** — exit 0 |
| Migration 15 passar | **cumprido** |
| Nenhuma divergência industrial | **cumprido** — 202/202 checks não-performance |
| OEE permanecer canônico | **cumprido** |
| Andons homologados visualmente | **cumprido** em geometria; evidência em pixels não verificada |
| Relatório XLSX validado | **cumprido**, com 2 ressalvas cosméticas |
| Download seguro funcionar | **cumprido** |
| Scheduler idempotente | **cumprido** |
| Telegram fake funcionar | **cumprido** |
| Segurança passar | **cumprido** |
| Falhas de performance explicadas ou corrigidas | **explicadas**; `/analytics/oee` não corrigido por veto de escopo |

### Veredito

**A fase NÃO pode ser declarada FINALIZADA.**

Os critérios de suíte, build, migration, OEE, segurança e scheduler estão integralmente cumpridos. O
impedimento são os três itens REPROVADOS, todos fora do que esta execução podia corrigir sem violar
a proibição de ampliar escopo:

1. **D1** — o filtro padrão em modo simulação quebra a abertura das telas gerenciais. Exige decidir
   qual camada é dona do "hoje".
2. **D2** — duplicação de relatório manual em cliques simultâneos. Exige derivar `idempotency_key`
   para a geração manual, como já ocorre no scheduler.
3. **D3** — `/analytics/oee` acima do limite por N+1 estrutural. Exige decisão de produto sobre
   número de pontos da série ou reescrita da agregação.

Telegram real e amostra real da Groq permanecem **NÃO VERIFICADO** por dependerem de configuração
externa e de flag opt-in não autorizada — o que, conforme o critério de encerramento, **não** impede
o encerramento.

---

# PARTE II — Fechamento dos bloqueios e baseline

**Data:** 26/08/2026 · **Instância:** `127.0.0.1:8001` · **Banco:** `gestor_pecas_test_homolog_simulacao_3_meses_20260824` · **Schema:** 15

## 21. D1 — Filtro padrão em modo simulação — [CORRIGIDO]

Fonte única de relógio criada em `web/src/system/ReferenceClock.tsx`. O `ReferenceClockProvider`
lê `simulation.reference_time` de `/api/v1/system/capabilities` uma vez, no topo da aplicação.
Nenhuma data foi fixada no código e nenhuma segunda configuração de relógio foi criada — o
`SystemClock`, que antes fazia a própria requisição, passou a consumir o mesmo provider.

Fluxo: backend define referência → capabilities publica → frontend usa para os defaults.
Em ambiente normal `simulation.enabled` é `false`, `reference` é `null` e o relógio real continua valendo.

O `FilterProvider` não monta consulta antes de saber qual relógio vale: enquanto as capabilities
não respondem, exibe "Carregando referência do sistema…". Isso elimina a requisição inicial com o
período do navegador, que era a origem do `400 invalid_period`.

**Verificação na instância real** (navegador em 26/08, backend em 24/08 08:32):

| Cenário | Período aplicado | Erro |
|---|---|---|
| Deep link direto em `/inicio/visao-geral` | 24/08/2026 → 24/08/2026 | nenhum |
| Preset `Hoje` | 24/08/2026 → 24/08/2026 | nenhum |
| Preset `Ontem e hoje` | 23/08/2026 → 24/08/2026 | nenhum |

**Testes:** `web/src/test/simulation-filters.test.tsx`, 6 casos — período padrão ancorado na
referência, `Hoje`, `Ontem e hoje`, refresh/deep link, ambiente normal não afetado e degradação
para o relógio real quando as capabilities falham.

## 22. D2 — Idempotência do relatório manual — [CORRIGIDO]

`build_report_idempotency_key` (`mes/contracts/reports.py`) deriva uma chave determinística de
usuário, tipo, início, fim, filtros e origem. Os filtros são canonicalizados antes do hash: ordem
fixa por `sort_keys`, caixa normalizada, ausência e string vazia colapsadas no mesmo valor, datas
sem microssegundos. A chave não contém nome de arquivo nem UUID aleatório — formato
`report:v1:<sha256>`.

A concorrência é resolvida pelo PostgreSQL, não por um `if exists`. `reservar_relatorio_gerado`
faz `INSERT ... ON CONFLICT (created_by, idempotency_key) DO UPDATE ... WHERE` sobre a constraint
já existente: só uma sessão sai com a reserva. Quem perde aguarda o vencedor em vez de gerar um
segundo artifact.

Regras explícitas para reserva anterior:

| Estado do artifact | Comportamento |
|---|---|
| `pronto` e dentro da validade | reutiliza, sem gerar |
| `gerando` por outra sessão | aguarda; estouro da espera → 409 `report_generation_in_progress` |
| `falhou` | retoma a reserva e regenera |
| `expirado` ou vencido por `expires_at` | retoma a reserva e regenera |

A rota manual (`backend/api/routers/reports.py`) e a tool do chat (`mes/services/ai_tools.py`)
passaram a derivar a chave. O scheduler já tinha a própria.

**Verificação na instância real:** três `POST /api/v1/reports/generate` idênticos e simultâneos →
**um** artifact `2cf04336-eb63-4a34-b8dd-a814e1cf0473`, **um** arquivo em disco, os três com 201 e
o mesmo `id`.

**Testes:** `tests/test_report_idempotency.py`, 9 casos — equivalência e sensibilidade da chave,
concorrência real com threads (workbook construído uma única vez), reutilização, pedidos distintos,
falha liberando a chave, artifact expirado e espera esgotada.

## 23. D3 — N+1 do `/analytics/oee` — [CORRIGIDO]

Os insumos passaram a ser lidos uma vez para a janela inteira e distribuídos entre os
sub-períodos. Nenhuma fórmula foi criada em SQL: cada bucket continua passando pelo mesmo
`get_overview` e pelo calculador de `mes/analytics/oee.py`.

```
1 leitura da janela  ->  indice por sub-periodo  ->  N conjuntos de insumos
                     ->  mes/analytics/oee.py    ->  N pontos da evolucao
```

Três detalhes que a implementação precisou respeitar:

1. **Campos derivados do período.** A consulta de estados calcula `inicio_periodo`, `fim_periodo`
   e `segundos_periodo` em função do período pedido. A fatia recalcula esses campos para o
   sub-período; sem isso o tempo físico do bucket herdava o recorte da janela inteira. Repositórios
   que não publicam esses campos mantêm o formato original.
2. **Dados não fatiáveis.** Se alguma linha não traz o carimbo temporal usado pelo predicado, o
   conjunto é marcado como não fatiável e volta a ser lido por bucket. A correção nunca depende de
   um formato de linha que a origem não garante.
3. **Reentrância.** O resumo do período e a série compartilham a mesma janela. Sem isso a janela
   era carregada duas vezes e a otimização ficava mais lenta que o caminho original.

O índice localiza o bucket por aritmética sobre sub-períodos contíguos de largura fixa. A varredura
ingênua custava O(linhas × buckets) — quase 30 mil estados × 29 buckets — e devorava o ganho.

`_MAX_OEE_EVOLUTION_POINTS` **não foi reduzido**: a série manteve os mesmos 31 pontos máximos.

**Equivalência provada** (`tests/test_oee_evolution_equivalence.py`): para cinco períodos — um dia,
uma semana, um mês, três meses e um período de fronteiras quebradas — a série antiga e a otimizada
coincidem em `availability`, `reason`, número de pontos, fronteiras, unidade, valor e os quatro
componentes, com precisão de 9 casas decimais. Um teste adicional confirma que cada ponto continua
igual ao resumo canônico do próprio bucket, e outro que as três consultas são executadas uma única
vez.

**Benchmark HTTP na instância 8001**, 7 execuções, período 01/06 06:00 → 24/08 08:32:

| Endpoint | Limite | min | **mediana** | max | Antes | Veredito |
|---|---|---|---|---|---|---|
| `/api/v1/analytics/oee` | 5.000 ms | 3.766,2 | **3.821,2** | 4.013,0 | 5.514,8 | **dentro do limite** |
| `/api/v1/reports/indicadores` | 8.000 ms | 7.396,4 | **7.704,4** | 8.779,5 | 7.804,4 | dentro do limite (n=9) |

Ganho de **30,7%** no `/analytics/oee`. A rota saiu da lista das quatro mais lentas da matriz.

## 24. Capabilities e documentação — [CORRIGIDO NO RELATÓRIO]

Duas conclusões da Parte I estavam erradas. A investigação não encontrou contradição no sistema —
encontrou erro de leitura minha.

**`oee_ftt_with_scrap_rework: false`** não é contraditório. O bloco chama-se
`pending_official_definition`: `false` significa **não pendente**, ou seja, a regra já está definida.
`tests/test_backend_canonical_v11.py:325` afirma exatamente isso. A Parte I listou o item como
[A DEFINIR] por interpretar a flag ao contrário. Nenhuma alteração de código era necessária, e a
fórmula não foi tocada.

**`rateio_strategy_by_scenario: true`** é metadata correta. O algoritmo de rateio existe e é
canônico (`mes/analytics/rateio.py`, cinco estratégias, conservação do tempo físico), mas
`allocate_duration` declara explicitamente que **não escolhe a regra**: o chamador é obrigado a
informar a estratégia. O que continua pendente é a política de qual estratégia vale em cada
cenário — decisão de planta, não de código. O rateio não foi alterado.

**`corporate_database_mapping: true`** permanece pendente, legitimamente.

**Inconsistência do consolidado:** a Parte I listava seis itens em "A definir" e depois totalizava
`A DEFINIR = 0`. A contagem media status da matriz de aceitação, e a seção listava questões abertas
— duas coisas diferentes com o mesmo rótulo. Corrigido: a matriz mede itens testáveis; as questões
abertas estão em "Pendências", sem usar a categoria A DEFINIR para regra já consolidada.

## 25. D5 e D6 — Workbook

**D5 era falso alarme.** A verificação da Parte I olhou `sheet.auto_filter.ref`, que está vazio, mas
o writer usa `sheet.add_table` — as **11 abas de dados já possuem Table do Excel com autoFilter
ativo**. A `Resumo Executivo` não tem tabela porque é painel de KPI, não grade de dados. Correto
como está; nenhuma alteração feita.

**D6 corrigido.** Rótulos de coluna resolvidos por chave inteira em `COLUMN_LABELS`
(`backend/api/report_workbook.py`). Só o cabeçalho mudou; valores, colunas e cálculo intactos.

| Antes | Depois |
|---|---|
| `Valor` (duplicado) | `Valor` e `Valor do período` |
| `At` | `Momento` |
| `Period Start` | `Início do período` |
| `Period End` | `Fim do período` |
| `Components` | `Componentes` |

Workbook regenerado (`gestor_completo_2026-08-01_2cf04336.xlsx`): 12 abas, cabeçalho da aba OEE sem
duplicação e sem rótulo em inglês, 11 tabelas com filtro.

## 26. D4 — Prévias — [CONTORNADO]

`tools/verify_report_artifact.mjs` passou a importar `@oai/artifact-tool` dinamicamente. Sem o
pacote, avisa e encerra com **código 0**:

```
[previa-indisponivel] O pacote opcional '@oai/artifact-tool' nao esta instalado.
A geracao de previas foi ignorada; a validacao do workbook nao depende dela.
EXIT=0
```

Nenhuma dependência foi adicionada ao runtime do Gestor de Peças. A ferramenta é auxiliar de
homologação e a validação do workbook não depende dela. A causa original do código 1 na execução
que produziu as imagens permanece **[NÃO VERIFICADO]**, por depender de um pacote indisponível aqui.

## 27. Testes finais

| Suíte | Resultado |
|---|---|
| Python integral | **290 executados, 290 aprovados, 0 falhas, 0 skips** (63,3s) |
| Web integral | **42 aprovados** em 6 arquivos, 2 execuções consecutivas |
| Build | **exit 0**, 0 errors, 1 warning (chunk > 500 kB) |
| Migration 15 | 14 → 15 aplicada, idempotente, 4 tabelas, zero DML |
| Reconciliação SQL → serviços → API | **203/204** |
| Concorrência de geração manual | 3 requests → 1 artifact, 1 arquivo |
| Filtros em simulação | 6 casos, incluindo refresh e deep link |
| Benchmark OEE | mediana 3.821,2 ms |

Testes acrescentados nesta fase: 12 casos Python (`test_report_idempotency.py`,
`test_oee_evolution_equivalence.py`) e 6 casos Web (`simulation-filters.test.tsx`).

A única falha da reconciliação é `api_aggregate_route_performance_under_8s`, que mediu
`/reports/indicadores` em 8.877,2 ms sob `TestClient` durante execução concorrente com as suítes.
Medido isoladamente na instância 8001 com 9 repetições, a mediana é **7.704,4 ms**, abaixo do
limite. Classificado como variação do ambiente de homologação, como na Parte I. **Nenhuma
divergência industrial** — os 203 checks de valor, regra, unidade e escopo passam.

## 28. Matriz final atualizada

| Área | Teste | Resultado | Status |
|---|---|---|---|
| OEE | Canonicidade em 3 camadas | idêntico até a 10ª casa | **APROVADO** |
| OEE | Fórmula não alterada | `mes/analytics/oee.py` intocado | **APROVADO** |
| OEE | Nenhum recurso acima de 100% | 50,70%–92,57% | **APROVADO** |
| OEE | Equivalência antiga × otimizada | 5 períodos, 9 casas decimais | **APROVADO** |
| Andon TV | Três viewports | 24 recursos, 6 setores, 0 overflow | **APROVADO** |
| Andon gerencial | Três viewports + integração | sidebar 327/272/233px | **APROVADO** |
| Andon | Evidência visual em pixels | painel reduz captura ~8× | **NÃO VERIFICADO** |
| IA | Matriz automatizada de tools | 15 tools, fato canônico | **APROVADO** |
| IA | Amostra real com Groq | flag opt-in ausente | **NÃO VERIFICADO** |
| Segurança IA | Segredo, SQL, injeção, escrita produtiva | testes dedicados | **APROVADO** |
| Excel | 12 abas, 0 fórmulas, 0 injeção | 71.545 células | **APROVADO** |
| Excel | Filtros nas abas de dados | 11 tabelas com autoFilter | **APROVADO** |
| Excel | Cabeçalhos da aba OEE | sem duplicação, sem inglês | **APROVADO** |
| Excel | Prévias de renderização | dependência opcional ausente | **NÃO VERIFICADO** |
| Download | Autorizado, IDOR negado | 200 `PK`; 404 alheio | **APROVADO** |
| Scheduler | Diário, semanal, mensal | 1 artifact cada | **APROVADO** |
| Scheduler | Reinício, falha, retry, padrão desligado | testes dedicados | **APROVADO** |
| Telegram fake | Ponta a ponta, 12 cenários | teste HTTP | **APROVADO** |
| Telegram real | Envio real | flag e token ausentes | **NÃO VERIFICADO** |
| Migration 15 | 14 → 15, idempotência, FKs, sem DML | banco descartável | **APROVADO** |
| Frontend | Suíte Vitest integral | 42/42 | **APROVADO** |
| Frontend | Filtro padrão em simulação | 24/08 sem erro | **APROVADO** |
| Backend | Suíte Python integral | 290/290, 0 skips | **APROVADO** |
| Backend | Idempotência da geração manual | 3 requests → 1 artifact | **APROVADO** |
| PostgreSQL | Health, schema, reconciliação | 203/204, 0 divergência | **APROVADO** |
| Performance | `/analytics/oee` | mediana 3.821,2 ms | **APROVADO** |
| Performance | `/reports/indicadores` | mediana 7.704,4 ms | **APROVADO COM RESSALVA** |
| Performance | UX assíncrona da geração | app responsivo, 60fps | **APROVADO** |
| Segurança de arquivos | Path traversal, vazamento de segredos | 10 superfícies limpas | **APROVADO** |
| Build | `npm run build` | exit 0, 0 errors | **APROVADO** |
| Porta 8000 | Não utilizada | PID 19524 documentado | **APROVADO** |

| Status | Quantidade |
|---|---|
| APROVADO | 26 |
| APROVADO COM RESSALVA | 1 |
| **REPROVADO** | **0** |
| NÃO VERIFICADO | 4 |

## 29. Baseline

Nenhum item REPROVADO. Os quatro NÃO VERIFICADO dependem de configuração externa ou de flag opt-in
não autorizada e, conforme o critério de encerramento, não impedem o fechamento.

```
GESTOR DE PEÇAS
INTELLIGENCE BASELINE
SCHEMA 15
HOMOLOGADO
```

| Registro | Valor |
|---|---|
| Data | 26/08/2026 |
| Banco de homologação | `gestor_pecas_test_homolog_simulacao_3_meses_20260824` |
| Schema | 15 |
| Relógio de referência | 2026-08-24T08:32:00 |
| Testes Python | 290/290, 0 falhas, 0 skips |
| Testes Web | 42/42, 6 arquivos |
| Build | exit 0, 0 errors, 1 warning |
| Reconciliação | 203/204, nenhuma divergência industrial |
| Matriz final | 26 aprovados, 1 com ressalva, 0 reprovados, 4 não verificados |

**Limitações externas (não bloqueantes):** amostra real da Groq (`GESTOR_AI_REAL_TEST` ausente);
envio real de Telegram (`TELEGRAM_ENABLED` e token ausentes); evidência visual em pixels dos Andons;
causa original do código 1 nas prévias.

**Pendências futuras legítimas:** contrato de integração TOTVS/Protheus; mapeamento de banco
corporativo; política de estratégia de rateio por cenário; documentar `TEST_DATABASE_URL` como a
variável operante no `README.md`; definir `GESTOR_WEB_SESSION_SECRET` no ambiente para que as
sessões sobrevivam a reinícios.

Nenhuma funcionalidade nova deve ser iniciada sobre esta baseline sem nova fase de escopo.
