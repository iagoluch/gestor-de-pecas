# Inventário — Dashboard da Diretoria e Auditoria Analítica (Etapa 1)

Data: 10/11/2026 · Origem: documento "Gestor de Peças — Dashboard da Diretoria e Auditoria Analítica", rev. 01.
Escopo: somente leitura do código (web/, backend/, mes/). Nada foi alterado. Identidade visual fica como está hoje (decisão do usuário, 10/11/2026).

Os anexos A–D (abaixo) têm o detalhe por tela: componente, endpoints, serviço, filtros, colunas, KPIs, exportação, permissão e destino proposto (tipos 01–21 / DASH / OPER).
Os itens marcados "conferido" foram checados diretamente no código durante a consolidação. Os demais vêm do levantamento e devem ser conferidos quando a tela for migrada.

## 1. Conclusões que mudam o plano

1. **OEE tem uma fonte única** (`mes/analytics/oee.py`, chamada por `ManagementService.get_overview`). Setup não penaliza Disponibilidade nem Performance (conferido, `oee.py:58-68`). OEE = Disponibilidade × Performance × FTT. A Auditoria e o Dashboard devem consumir essa função, nunca recalcular.
2. **"Tempo trabalhado" tem três bases diferentes**: OEE (produção + setup + retrabalho + atividade sem OP), MTBF (sem retrabalho) e Capacidade (sem atividade sem OP). Isso precisa de decisão antes de exigir que o Dashboard bata com a Auditoria. → Pergunta P1.
3. **"Utilização" aparece com três fontes**: Horas & Utilização (simulação), OEE (`kpis_estendidos.utilization`, igual à Disponibilidade) e Capacidade (carga ÷ calendário). → Pergunta P2.
4. **Não há instante de referência (as_of)** nas respostas analíticas, e existem três relógios no código (`agora_db()`, `self._now()`, `datetime.now()`). O critério de aceite "mesmo instante de referência" exige introduzir isso no contrato.
5. **Cálculos feitos na tela** (frontend) que precisam ir para o servidor: Desvio % do Tempo padrão, média ponderada da Cronoanálise, somas da Capacidade, variações da Visão Geral, média por recurso em Relatórios > Perdas. Sem isso, Dashboard e Auditoria podem divergir.
6. **Zeros sem significado**: "produzido" da Diretoria vira 0 quando falta dado (conferido, `director_summary.py:162`); média da Cronoanálise vira 0 sem amostra. Contradiz o critério "zero ≠ sem dados".
7. **Padrão × Real e Cronoanálise** dividem o tempo recortado ao período pelas boas do apontamento inteiro → apontamento que atravessa o período distorce o tempo por peça.
8. **Possível dupla contagem**: nesting antigo sem início/fim soma em produção sem checar sobreposição (`management.py:354`, `:403`).
9. **MTTR**: por recurso inclui reparos em andamento; o geral só conta concluídos.

## 2. Telas que NÃO são consulta (ficam OPER)

- **Consulta de OP**: grava e chama o Protheus (POST /protheus, /steps, /deactivate). Fica na Produção; a Auditoria só leva até ela.
- **Envios ao Protheus**: "Reenviar" dispara novo envio real sem confirmação (conferido: só "Descartar" pede motivo, `TotvsOutboxPage.tsx:56`). Na Auditoria (tipo 19) entra só a consulta; as ações ficam na tela atual.
- **Decisão de RNC, Cadastro, Alterações (Desfazer), Chamadas do IagoDev (remover contato), Sistema (reiniciar build)**: ações que ficam nos fluxos atuais.

## 3. Permissões e dados pessoais

- O backend confere permissão nas rotas admin lidas; não foi achada tela protegida só pelo frontend.
- Chamadas da Gestão mostra e-mail e crachá de quem chamou a qualquer conta de gestão; Alterações e Log mostram usuário; Chamadas do IagoDev mostra ID do Telegram. A Auditoria precisa de permissão **por tipo de relatório**, herdando a do módulo de origem.
- Custo em R$ existe só na Diretoria (`require_diretoria_user`).

## 4. Exportação hoje

Só Relatórios (4 abas, .xlsx técnico e simples) e Produção realizada exportam. Há CSV no backend (`routers/reports.py:227`) sem uso na tela. Nenhuma tela de Análises exporta.

## 5. Divergência documental encontrada

`AGENTS.md:122` diz "Refugo não completa a quantidade planejada da OP". O código (`mes/domain/manufacturing_rules.py`) e `docs/REGRAS_MANUFATURA_CANONICAS.md:25-38` dizem que **boas + refugo** completa a meta, e o próprio documento canônico registra que a regra antiga foi substituída. O AGENTS.md está desatualizado (conferido). → Pergunta P4.

## 6. Outros pontos

- Mesmo conceito por endpoints diferentes: Inconsistências da Visão Geral × Auditoria > Alertas; Planejado da Visão Geral (simulação) × Planejado × Realizado. Auditoria > Alertas chama `facade.auditoria` duas vezes.
- Filtro escondido: OPs em andamento tem filtro de status fixo no backend (`operations.py:113`).
- Paradas e Setup são uma rota só; a aba não vai para a URL.
- 9 rotas antigas só de redirecionamento (`App.tsx`); Andon e Mapa do menu apontam para redirect.
- Campo `evidence` de Qualidade existe na API e não aparece na tela.

## 7. Perguntas para o usuário

- **P1** Qual base de "tempo trabalhado" o Dashboard mostra? Proposta: manter as três, cada uma com nome próprio (ex.: "Tempo produtivo (OEE)", "Tempo de operação (MTBF)", "Carga (Capacidade)"), em vez de unificar fórmula.
- **P2** "Utilização" oficial: carga ÷ calendário (Capacidade). A de `kpis_estendidos` (igual à Disponibilidade) deixa de se chamar Utilização.
- **P3** O tipo 19 (Envios) na Auditoria mostra só consulta, com link para a tela atual onde ficam Reenviar/Descartar? E Reenviar passa a pedir confirmação?
- **P4** Corrigir o AGENTS.md para a regra vigente (boas + refugo completa a meta)?

### Decisões do usuário (10/11/2026)

- P1: manter as três bases, cada uma com nome próprio. Nenhuma fórmula muda.
- P2: "Utilização" oficial = carga ÷ calendário (Capacidade). O valor de `kpis_estendidos.utilization` passa a ser chamado Disponibilidade.
- P3: tipo 19 na Auditoria é só consulta. "Reenviar" passou a pedir confirmação (`TotvsOutboxPage.tsx`).
- P4: AGENTS.md corrigido para a regra vigente.

## 8. Próximo passo (Etapa 2)

Estrutura da Auditoria (seletor de tipo, filtros comuns, tabela, detalhe, exportação) com os tipos 01 Eventos de Status e 02 Eventos de Produção, comparando linha a linha com as telas atuais. Introduzir `as_of` no contrato desses dois tipos.

---


# Anexo — inv_A_producao_auditoria

# Inventário das telas (somente leitura) — status: PARCIAL

Legenda: "parcial" = ainda não confirmado com leitura completa. Caminhos de frontend relativos a `web/src/`; backend relativos a `backend/api/routers/`; fachada em `mes/services/frontend_facade.py`.

## Tela inicial > Visão Geral — `/inicio/visao-geral` (parcial)
- Componente: `pages/ManagementOverviewPage.tsx:133`
- O que responde: visão gerencial do período (OEE, disponibilidade, performance, FTT, produção boa, planejado×realizado, exceções, setores, alertas ao vivo, chamadas).
- Endpoints:
  - `GET /api/v1/management/overview` → `management.py:69` → `facade.inicio` (`frontend_facade.py:299`) → `management_insights`, `ManagementService`
  - `GET /api/v1/management/overview/trend` → `management.py:78` → `facade.inicio_tendencia` (`:407`) → `ManagementService` (`management.py:~1429`: `previous`, `sector_summary`, `recent_events`)
  - `GET /api/v1/andon` → `andon.py:15` → `facade.andon` (`:908`)
  - `GET /api/v1/chamadas/admin/historico` → `chamadas.py:416` → `database.listar_chamadas(limite=200)` (sem fachada)
- Filtros: período e setor vindos de `useManagementFilters` (padrão: período atual; não verificado o padrão exato).
- Cards/KPIs (principais):
  - OEE, Disponibilidade, Performance, FTT → backend (`management.py` via `inicio`); frontend só formata.
  - Setinha de variação dos KPIs (pp) → frontend `kpiTrend` (`ManagementOverviewPage.tsx:44-50`) usando `trend.previous`.
  - Variação de produção boa (%) → frontend `quantityTrend` (`:52-57`).
  - Sparklines → frontend `sparkOf` (`:~283`) a partir de `trend.points`.
  - Produção boa → `data.production.good` (backend).
  - Bloco Planejado/Realizado/Atingimento/Utilização/Produtividade/AE → `data.simulation` (backend: `management.py:580-593`, `:856`).
  - Gráfico Planejado×Realizado → `trend.points` (frontend só desenha).
  - "Agora na fábrica" (eventos recentes agrupados por setor e estado) → frontend `groupLiveSectors` (`:92-109`) sobre `trend.recent_events`.
  - "Alertas ao vivo" → frontend filtra `andon` por `state.category === "parada"` e corta em 4 (`:312-315`).
  - Tabela de setores: OEE do setor vem de `data.sector_kpis` (backend); recursos do setor são unidos no frontend por `resource_kpis.filter(sector)` (`:529-531`).
  - "Inconsistências de dados" → `data.audit.open_issues` (backend `management.py:837`, `_load_open_issues` `:1656`).
  - "Chamadas da gestão" → contagem e lista de `/chamadas/admin/historico`.
- Exportação: não encontrado.
- Permissão: aba comum (sem `levels`/`adminOnly` em `config/navigation.ts:161-172`). Backend: `require_management_user` (`management.py:69-…`); `/andon` usa `require_andon_user` (`andon.py:18`). Chamadas: `require_management_user` (`chamadas.py:418`).
- Vazio/erro: `EmptyState`/`LoadingState`/`ErrorState`; "Dados insuficientes" quando `trend` falta ou `simulation` é nulo (`:385-393`); trend com `availability === "sem_registros"` vira `null` (`:217`). Distinção zero × sem dado: parcial (usa `availability` e `humanizeSystemState`).
- Mesmo dado em outra tela:
  - `facade.inicio` é reutilizado por `relatorio("gerencial")` (`frontend_facade.py:1085`) → Relatórios > Gerencial.
  - Produção boa/refugo/retrabalho também em Relatórios > Gerencial e Consulta de OP/Produção realizada (`producao_realizada`).
  - "Inconsistências" (`open_issues`) × Auditoria > Alertas (`/management/alerts`, campo `issues`) — fontes diferentes, ver Observação.
  - Planejado (`simulation`) × Produção > Planejado×Realizado (`/orders/planned-vs-actual`) — fontes diferentes, não comparado ainda.
- Destino proposto: DASH (síntese executiva). Blocos de alerta ao vivo/chamadas podem ficar em OPER. (Decisão do orquestrador.)
- Observação:
  - Cálculo no frontend: variação (pp e %), agrupamento de eventos recentes por setor, filtro de paradas do andon, união recurso↔setor.
  - Mesmo conceito, endpoints diferentes: inconsistências (`open_issues` na visão geral × `issues` em `/management/alerts`); planejado (`simulation` × `/orders/planned-vs-actual`). Precisa comparar valores antes de unificar.
  - Campos que só existem aqui: `sector_highlights` (`frontend_facade.py:301`), `simulation`, `trend.sector_summary`.

## Consulta Operacional — `/consulta-operacional/*` (parcial)
### Visão Geral — `/consulta-operacional/visao-geral`
- Componente: `pages/operations/OperationsPages.tsx:78`
- Endpoint: `GET /api/v1/operations/overview` → `operations.py:61` → `facade.consulta_operacional(..., somente_recursos_em_uso=True)` (`frontend_facade.py:462`) → `CalendarService`, `self.db`.
- Filtros: `dailyQuery` / período (parcial).
- Cards/KPIs: não lidos ainda.
- Exportação: não encontrado.
- Permissão: `require_management_user` (`operations.py:64`).
- Destino proposto: OPER (parcial).

- Nota: `/consulta-operacional/tempo-mes` redireciona para `/analises/horas-utilizacao` (`App.tsx:198`). O bloco "Tempo MES" (`OperationsTimeSection`, `OperationsPages.tsx:249`, `GET /api/v1/operations/time`) é renderizado em Análises > Horas & Utilização (`AnalyticsPages.tsx:446`), não em Consulta Operacional. Fica fora desta lista; ver inventário de Análises.

### Recursos — `/consulta-operacional/recursos`
- Componente: `pages/operations/OperationsPages.tsx:140`
- Endpoint: `GET /api/v1/operations/resources?page=1&page_size=200` → `operations.py:82` → mesma `facade.consulta_operacional` (`:462`), paginado no router.
- Observação: mesma chamada de fachada da Visão Geral (dois endpoints, mesmo cálculo). Paginação feita no router.
- Destino proposto: OPER (parcial).

### OPs em andamento — `/consulta-operacional/ops-em-andamento`
- Componente: `pages/operations/OperationsPages.tsx:192`
- Endpoint: `GET /api/v1/operations/orders?page=1&page_size=…` → `operations.py:103` → `facade.ordens_producao` (`frontend_facade.py:949`) + filtro de status fixo `{aguardando, em processo, parada, setup, retrabalho}` no router (`operations.py:113`).
- Observação: o filtro de status é do backend, escondido da tela (o usuário não vê a lista de status aplicada). Mesma fonte de `/orders` (Produção > Execução).
- Destino proposto: OPER.

## Produção — `/producao/*` (parcial)
### Consulta de OP — `/producao/ordens`
- Componente: `pages/production/OrderConsultationPage.tsx:302` (prefixo `/api/v1/order-consultation`, `:20`)
- Endpoints (`backend/api/routers/order_consultation.py`):
  - `GET /search?q=` (`:58`) → sugestões de OP ao digitar (mínimo de caracteres, `:312`).
  - `GET /{codigo_op}` (`:101`) → detalhe da OP (`:314`).
  - `POST /{codigo_op}/protheus` (`:76`, CSRF) → checagem contra o Protheus (`OrderConsultationPage.tsx:327`). Integração externa.
  - `POST /{codigo_op}/steps` (`:113`, CSRF) → cria etapa (`:246`). Escrita.
  - `POST /{codigo_op}/steps/{step_id}/deactivate` (`:133`, CSRF) → desativa etapa com motivo (`:363`). Escrita.
- Observação: é a única tela da lista com escrita e chamada ao Protheus. Não é só consulta. Veto de Haiku e risco R3 (integração/dado real). Não li o service nem as tabelas (parcial).
- Destino proposto: OPER (fica onde está; não entra na Auditoria).

### Execução das OPs — `/producao/execucao`
- Componente: `pages/production/ProductionPages.tsx:53`
- Endpoint: `GET /api/v1/orders?...&page=1&page_size=…&search=` (`ProductionPages.tsx:57`) → `orders.py:30` → `facade.ordens_producao` (`:949`), filtro `status` e `search` no router (`_filter_items`).
- Observação: mesma fonte de Consulta Operacional > OPs em andamento, com filtros diferentes.
- Destino proposto: OPER.

### Produção realizada — `/producao/realizada`
- Componente: `pages/production/ProductionPages.tsx:107`
- Endpoint: `GET /api/v1/orders/production` (`ProductionPages.tsx:109`) → `orders.py:49` → `facade.producao_realizada` (`frontend_facade.py:1032`) → `self.management`, `self.analytics`.
- Exportação: confirmado. `ProductionCompletedPage` põe `DownloadAction type="producao"` no cabeçalho (`ProductionPages.tsx:112`) → `/api/v1/reports/producao/export.xlsx` (técnico e simples). O backend monta `relatorio("producao")` (`frontend_facade.py:1083`): `producao_realizada` + `ordens_producao`.
- Destino proposto: DASH ou OPER (decisão pendente).

### Planejado × Realizado — `/producao/planejado-realizado`
- Componente: `pages/production/ProductionPages.tsx:167`
- Endpoint: `GET /api/v1/orders/planned-vs-actual?...&page=1&page_size=…` (`ProductionPages.tsx:169`) → `orders.py:58` → `facade.producao(filters)["planejado_x_realizado"]` (`frontend_facade.py:926`).
- Observação: planejado aqui vem de `planejado_x_realizado`; na Visão Geral vem de `simulation` (`management.py`). Confirmar se são o mesmo número.
- Destino proposto: DASH (síntese) + OPER (detalhe).

## Auditoria — `/auditoria/*` (parcial)
### Eventos de Status — `/auditoria/eventos-status`
- Componente: `pages/audit/AuditPages.tsx:204`
- Endpoint: `GET /api/v1/audit/status-events?...` (`AuditPages.tsx:221`) → `audit.py:35` → `facade.eventos_status` (`frontend_facade.py:1282`) → `self._estados_periodo`, `self.db`.
- Filtros de tabela: `evento_recurso`, `evento_status`, `evento_classe`, `evento_op`, `em_aberto` (server-side, `audit.py:41-45`).
- Destino proposto: 01.

### Eventos de Produção — `/auditoria/eventos-producao`
- Componente: `pages/audit/AuditPages.tsx:303`
- Endpoint: `GET /api/v1/audit/production-events?...` (`AuditPages.tsx:305`) → `audit.py:54` → `facade.eventos_producao` (`frontend_facade.py:1299`) → `_paged_events` (`audit.py`).
- Totais no frontend: tipo do `EventsPage` tem `eventos`, `quantidade_boa`, `quantidade_refugo`, `quantidade_retrabalho`, `quantidade_sem_evento` (`AuditPages.tsx:305`). Origem dos totais: não confirmado se são do backend.
- Destino proposto: 02 (e 06 para boa/refugo/retrabalho).

### Alertas e inconsistências — `/auditoria/alertas-inconsistencias`
- Componente: `pages/audit/AuditPages.tsx:346`
- Endpoints (4 chamadas na mesma tela):
  - `GET /api/v1/management/alerts` (`AuditPages.tsx:348`) → `management.py:103` → `facade.auditoria` (`:1268`), devolve `items = issues`, `count`, `by_severity`, `reliability_percentage`.
  - `GET /api/v1/management/internal-alerts` (`AuditPages.tsx:349`) → `management.py:508` → `InternalAlertService.listar` (sem fachada).
  - `GET /api/v1/audit?page=1&page_size=200` (`AuditPages.tsx:350`) → `audit.py:64` → `facade.auditoria` (mesma chamada de `/management/alerts`).
  - `GET /api/v1/traceability/inspection-waivers?page=1&page_size=200` (`AuditPages.tsx:351`) → `traceability.py:65` → `facade.inspecoes_dispensadas` (`:1333`).
- Observação: `facade.auditoria` é calculado duas vezes na mesma tela (`/management/alerts` e `/audit`). Risco de números diferentes se o cálculo não for idêntico. Não comparado.
- Destino proposto: 15 (e 07 para inspeções dispensadas, 17 para alterações via `/audit`).

### Confiabilidade dos dados — `/auditoria/confiabilidade`
- Componente: `pages/audit/AuditPages.tsx:470`
- Endpoint: `GET /api/v1/audit/reliability?...` (`AuditPages.tsx:472`) → `audit.py:80` → `facade.auditoria` (mesma fonte de `/audit` e `/management/alerts`).
- Campos: `records_analyzed`, `resource_states_analyzed`, `rateio_sessions_analyzed`, `by_severity`, `reliability_percentage`, `reliability_reason`, `physical_state_source`.
- Destino proposto: 16.

## Relatórios — `/relatorios?tipo=…` (uma página, 4 abas)
- Componente: `pages/reports/ReportsPages.tsx:196` (abas em `:203-210`; tipo lido de `?tipo=`, padrão `gerencial`, `:198`)
- Endpoint de dados (todas as abas): `GET /api/v1/reports/{tipo}` (`ReportsPages.tsx:200`) → `reports.py:189` → `facade.relatorio` (`frontend_facade.py:1083`).
- Exportação (todas as abas): botões "Export técnico" e "Export simples" (`ReportsPages.tsx:77-101`) chamam `GET /api/v1/reports/{tipo}/export.xlsx?…&modo=tecnico|simples` (`reports.py:254`, `build_report_workbook`). Download pelo cliente `api.download` (`api/client.ts:106`). Nome local: `relatorio_{tipo}_{modo}.xlsx`.
- Exportação extra no backend: `GET /api/v1/reports/{tipo}/export.csv` (`reports.py:227`), CSV `;` com BOM. Não há uso no frontend (busca em `web/src`: nenhuma).
- Filtros: os mesmos de `useManagementFilters` (`ReportsPages.tsx:199`); exportação usa a mesma `query`.

### Relatórios > Gerencial (`?tipo=gerencial`)
- Backend: `relatorio("gerencial")` → `{overview: self.inicio(filters)}` (`frontend_facade.py:1085`). Mesma fonte da Tela inicial > Visão Geral.
- Cards: Produção boa, Refugo, Retrabalho (`ReportsPages.tsx:110-112`), OEE (`:113`). Valores do backend.
- Tabela "Setores": Produção boa, Refugo, Retrabalho, Tempo produtivo (`ReportsPages.tsx:116-122`). `Tempo produtivo` formatado no frontend a partir de `tempo_produtivo_segundos`.
- Destino proposto: DASH (síntese).

### Relatórios > Perdas (`?tipo=perdas`)
- Backend: `paradas`, `setup`, `qualidade`, `tempos`, `losses` (`frontend_facade.py:1083-1148`; `analise()` em `:1166`, `_perdas_canonicas`).
- Cards: Tempo de parada, Ocorrências, Refugo, Retrabalho (`ReportsPages.tsx:131-136`).
- Cálculo no frontend: detalhe do card "Tempo de parada" usa `formatAveragePerResource(total, rows(by_resource).length)` (`ReportsPages.tsx:132`) → média = total ÷ número de recursos, feita no cliente.
- Tabela "Paradas por motivo" (`by_reason`, `:138-141`).
- Destino proposto: 04 (Paradas), 06 (Refugo/Retrabalho).

### Relatórios > Indicadores (`?tipo=indicadores`)
- Backend: `analytics` = `tempos`, `qualidade`, `capacidade`, `confiabilidade`, `oee` via `analise()`; `kpis`, `kpis_estendidos`, `kpi_time_bases`, `kpi_contract`, `recursos` de `management.get_overview` (`frontend_facade.py:1148-1165`).
- Cards: OEE, FTT, Tempo registrado, Utilização (`ReportsPages.tsx:153-156`).
- Cálculo no frontend: detalhe "Tempo registrado" via `formatRecordedTimeDetail(..., rows(time.by_resource).length)` (`:155`); "Utilização" é só formatação de `capacidade.utilizacao_percentual` (`:156`).
- Bloco "Confiabilidade e capacidade": MTBF, MTTR, Quebras, Utilização (`:158-165`). MTBF/MTTR/falhas vêm de `analytics.confiabilidade`.
- Destino proposto: 11 (OEE/FTT), 10 (Utilização), 12 (MTBF/MTTR).

### Relatórios > Dados analíticos (`?tipo=dados_analiticos`)
- Backend: `orders` = `ordens_producao`, `audit` = `auditoria`, `nestings` = `nestings` (`frontend_facade.py:1083-1148`, bloco `dados_analiticos`).
- Cards: Ordens (conta de `orders.items`), Inconsistências (`audit.count`), Nestings (`nestings.count`), Período (`periodo.inicio`/`fim` cortados em 10 caracteres, `ReportsPages.tsx:176`).
- Tabela "Ordens — dados analíticos": OP, Produto, Operação, Setor, Recurso, Boas, Refugo, Status (`:178-188`). Não mostra nestings nem alertas na tela, mas o Excel pode trazer.
- Destino proposto: 03 (OPs), 15 (inconsistências), 14 (nestings).

## Rastreabilidade — `/rastreabilidade/*` (parcial)
### OP / Produto — `/rastreabilidade/op-produto`
- Componente: `pages/traceability/TraceabilityPages.tsx:158`
- Endpoint: `GET /api/v1/traceability/orders/{op}` (`:160`) → `traceability.py:17` → `facade.rastreabilidade` (`:1330`) → `self.traceability` (`TraceabilityService`). Checa escopo de setor (`trace_in_scope`) e devolve 403 `trace_out_of_scope`.
- Permissão: `require_management_user` + escopo por setor (`traceability.py:20-25`).
- Destino proposto: 13 (Linha do tempo da OP) e 14 (lote).

### Lote / Material / Nesting — `/rastreabilidade/lote-material-nesting`
- Componente: `pages/traceability/TraceabilityPages.tsx:259`
- Endpoint: `GET /api/v1/traceability/nestings?…&page=1&page_size=200&search=…` (`:263`) → `traceability.py:29` → `facade.nestings` (`frontend_facade.py:1041`). Busca textual feita no router (`traceability.py:39-44`).
- Observação: a tela pede sempre `page_size=200`; não confirmado se há paginação na UI.
- Destino proposto: 14.

## Riscos (até aqui)
1. Cálculo no frontend: variação pp/% da visão geral, agrupamento de eventos recentes, média por recurso em Perdas e "Tempo registrado" em Indicadores, união recurso↔setor.
2. Mesmo número, endpoints diferentes: Inconsistências (`open_issues`, visão geral) × Alertas (`issues`); Planejado (`simulation`) × Planejado×Realizado (`planned-vs-actual`).
3. Auditoria > Alertas chama `facade.auditoria` duas vezes (`/management/alerts` e `/audit`), e Confiabilidade chama a mesma fachada de novo.
4. Campos só existem numa tela: `sector_highlights`, `simulation`, `trend.sector_summary` (visão geral).
5. Exportação: só .xlsx em Relatórios (técnico e simples, nas 4 abas). CSV existe no backend sem uso. Produção realizada usa tipo `producao` (não confirmado o botão).
6. Filtro de status escondido em OPs em andamento (`operations.py:113`).


# Anexo — inv_B_analises_diretoria

# Inventário B — Análises, Diretoria, Melhoria Contínua, Qualidade (parcial, em andamento)

Status: parcial. Feito: Análises (todas as 8 telas), Melhoria Contínua, Diretoria (Painel e Ficha em parte, Custos só pela rota). Pendente: Qualidade (Cotas padrão, SPC, Decisão de RNC), router de `/management/first-pieces`, exportações (busca global), Diretoria Ficha/Custos em detalhe.

## Menu (web/src/config/navigation.ts)

- Análises: linhas 209-223, todas as abas sem `levels` (visíveis a todos que veem o menu). Rotas `analises/*` sem guarda no App.tsx (linhas 215-222).
- Manufatura: linhas 257-267, `tabs: []` (seção vazia hoje). Nível `STANDARD_TIME_LEVELS`.
- Qualidade: linhas 269-283. Abas: Cotas padrão `/qualidade/cotas`, SPC `/qualidade/spc`, Decisão de RNC `/qualidade/rnc`; todas com `QUALITY_TEMPLATE_LEVELS` (admin/desenvolvedor + `qualidade`). Guarda: `RequireQualityTemplateAccess` (web/src/App.tsx:125, rotas 207-209).
- Diretoria: linhas 286-296, `DIRECTOR_LEVELS` (admin + `diretoria`). Guarda `RequireDiretoriaAccess` (App.tsx:156, rota 211).
- Melhoria Contínua: linhas 298-310, `IMPROVEMENT_LEVELS` (só admin) ou atribuído `melhoria_continua`. Guarda `RequireImprovementAccess` (App.tsx:138, rota 213).

## Análises

### Análises > OEE — `/analises/oee`
- Componente: `web/src/pages/analytics/AnalyticsPages.tsx:340` (gráfico em :214)
- O que responde: OEE do período, componentes (Disponibilidade, Performance, FTT), AE, Produtividade, Utilização, evolução do OEE por dia/bucket, perdas em tempo e peças.
- Endpoints: `GET /api/v1/analytics/oee` → `backend/api/routers/analytics.py:24` (alias `oee`) → `mes/services/frontend_facade.py:1166` (`analise("oee")`) → `mes/services/management.py:69` (`get_overview`) e `:943` (`get_oee_evolution`). Componentes vêm de `facade.inicio(...).kpis` em `analytics.py:49-55`. Tabelas/views: não rastreadas até o SQL ainda.
- Filtros: via `useManagementFilters()` (filters.query). Padrão e obrigatoriedade: não verificado.
- Colunas/campos: 4 cards (OEE, Disponibilidade, Performance, FTT/Qualidade); 3 cards extras (AE, Produtividade, Utilização); gráfico de evolução; lista "Onde o OEE está sendo perdido"; lista "Perdas por motivo" (fora de turno, parada planejada, não planejada, ritmo, refugo, retrabalho).
- Cards/KPIs: OEE/Disp/Perf/FTT → backend (`kpis` de `get_overview`). AE/Produtividade/Utilização → backend (`kpis_estendidos`).
- Cálculo no frontend: `lossLabel` faz `100 - valor` para dizer "p.p. de perda" (`AnalyticsPages.tsx:170-176`). Escala do eixo Y do gráfico calculada no frontend (`:225-226`).
- Exportação: não encontrado nesta tela.
- Permissão: menu sem nível. Backend: `require_management_user` + `management_read_slot` (`analytics.py:12,18`).
- Vazio/erro/indisponível: evolução com menos de 2 pontos mostra EmptyState "Dados insuficientes" (`:377-384`). Valor ausente vira "Dados insuficientes" via `availability` (`:186-188`). Erro sem dado: ErrorState (`:351`).
- Mesmo dado em outra tela: `components` e `losses` vêm de `facade.inicio` (Tela inicial > Visão Geral). OEE também é a "Eficiência" da Diretoria (`director_summary.py:166`), mesma fonte `get_overview`.
- Destino proposto: 11 (OEE/disp/perf/FTT) e 04/05 para a perda por motivo; DASH para o resumo.
- Observação: OEE vem de duas chamadas dentro do backend (`kpis` de `inicio` para componentes e `analise("oee")` para o OEE). Verificar se o valor é o mesmo.

### Análises > Horas & Utilização — `/analises/horas-utilizacao`
- Componente: `AnalyticsPages.tsx:408`
- O que responde: tempo registrado consolidado, tempo atribuído bruto, sobreposição removida, utilização (simulação), produção e resumo por setor.
- Endpoints: `GET /api/v1/analytics/hours-utilization` → `analytics.py:33` (alias `tempos`) → `frontend_facade.py:1166` (`analise("tempos")`) → `mes/services/industrial_analytics.py:47` (`time_breakdown`) + `_operations_time_extras` (`frontend_facade.py` ~1260) + `management.get_overview(...)["simulation"]` quando `simulation_mode`.
- Filtros: `useManagementFilters()`.
- Colunas: "Produção por recurso" (BarList, 12 primeiros); "Resumo por setor" (Setor, Produção, Setup, Paradas). Seção extra `OperationsTimeSection` (importada de `pages/operations/OperationsPages`, `:13`, usada em `:446`).
- Cards: Tempo registrado, Tempo atribuído bruto, Sobreposição removida (backend); Utilização (backend, `simulation.metrics.utilization`).
- Cálculo no frontend: conversão `Number(row.producao ?? 0)` e `formatHours` (`:416`, `:439-441`). Média por recurso via `formatAveragePerResource` (`:421`). Sem soma de KPI próprio.
- Exportação: não encontrado.
- Permissão: menu sem nível; backend como OEE.
- Vazio: `EmptyState` quando não há recurso (`:432`). Sem distinção explícita zero × sem dado nos cards de tempo.
- Mesmo dado em outra tela: `OperationsTimeSection` é o mesmo componente de Operações > Tempo (a própria tela comenta "mesmos ids de Operações > Tempo"). Rota antiga `consulta-operacional/tempo-mes` redireciona para cá (`App.tsx:198`).
- Destino proposto: 10 (capacidade/utilização) e 01/02 não se aplicam; 11 para utilização.
- Observação: "Utilização" aparece aqui (simulação), em OEE (`extended_metrics.utilization`) e em Capacidade ("Utilização do período"). São três números com o mesmo nome e fontes diferentes. Só aparece quando `simulation_mode` está ligado (`frontend_facade.py`, bloco `tempos`).

### Análises > Paradas & Setup — `/analises/paradas` (uma rota, duas abas por estado local)
- Componente: `AnalyticsPages.tsx:451` (`SegmentPage`), alternância por `useState` em `:452`. A aba NÃO muda a URL. `AnalyticsDowntimesPage` em `:537`.
- O que responde: Paradas (planejada, não planejada, ocorrências, maior parada, recurso mais parado, Pareto por motivo, tabela de ocorrências) e Setup (tempo total de setup, ocorrências, recurso com mais setup, setup mais longo, tempo por tipo de setup, tabela).
- Endpoints:
  - Paradas: `GET /api/v1/analytics/downtimes` → `analytics.py:24` (alias `downtimes`) com `paradas_tela` (`analytics.py:47`) → `frontend_facade.py:1207` (`paradas_tela`) → `industrial_analytics.py:178` (`downtimes`, exclui `automatica`) + `management.py:1003` (`physical_consolidation`).
  - Setup: `GET /api/v1/analytics/setups` → alias `setup` → `frontend_facade.py` (`analise("setup")`) → `industrial_analytics.py:188` (`setups`) → `_segment_summary` `:835` / `_segments` `:850`.
- Filtros: `useManagementFilters()`. A aba não é filtro de URL.
- Colunas da tabela: Recurso, Setor, Motivo, Classificação (programada/não programada ou tipo de setup), Início, Tempo, OP (link para `/rastreabilidade/op-produto`).
- Cards Paradas: Parada não planejada, Parada planejada, Ocorrências, Recurso mais parado, Maior parada. Cards Setup: Tempo total de setup, Ocorrências, Recurso com mais setup, Setup mais longo.
- Cálculo no backend: planejada/não planejada e a diferença com a lista (`frontend_facade.py:1207-1240`), com motivo de diferença.
- Cálculo no frontend: média por ocorrência = `listed_seconds / count` (`AnalyticsPages.tsx:500`). Pareto e ranking são só ordenação/corte (`:470-480`).
- Exportação: não encontrado.
- Permissão: menu sem nível; backend como OEE.
- Vazio: `EmptyState` nas listas (`:511`). "Nenhuma" / "Não determinado" como texto nos cards (`:501-506`).
- Mesmo dado em outra tela: `downtimes` alimenta Melhoria Contínua (`ImprovementPage.tsx:19`) e a Diretoria (`director_summary.py` usa `analytics.downtimes`). `paradas_tela` usa a mesma consolidação de Visão Geral (`physical_consolidation`).
- Destino proposto: 04 Paradas e 05 Setup (são listas de eventos com tempo). DASH para os cards de resumo.
- Observação: Paradas e Setup usam endpoints diferentes, e só Paradas tem a conta consolidada. Se a Auditoria juntar as duas, a conta consolidada precisa continuar disponível. Para a "Parada não planejada" há dois caminhos: `paradas_tela` (`downtime - planned` de `physical_consolidation`) e Diretoria (`_unplanned_stop_hours` de `overview.hours`). Não comparei se dão o mesmo número.

### Análises > Qualidade — `/analises/qualidade`
- Componente: `AnalyticsPages.tsx:539`. Seção "Primeira peça" em `:628` (`FirstPieceHistorySection`).
- O que responde: totais de Produção boa, Refugo, Retrabalho e FTT; refugo e retrabalho por motivo; qualidade por setor e por produto; histórico de primeira peça (Setup e checklist do posto) e autorizações por crachá.
- Endpoints: `GET /api/v1/analytics/quality` → `analytics.py:24` (alias `quality`) → `frontend_facade.py` (`analise("qualidade")`) → `industrial_analytics.py:192` (`quality`), fonte `_quantity_events` (`:971`) e `management.get_overview` para FTT (`:221`).
  - Primeira peça: `GET /api/v1/management/first-pieces` (`AnalyticsPages.tsx:629`). Router NÃO localizado ainda.
- Filtros: `useManagementFilters()`. Primeira peça não recebe filtro.
- Colunas: Qualidade por setor (Boas, Refugo, Retrabalho); por produto (mesmos); primeira peça (Inspecionada em, OP, Operação, Setor, Produto, Setup, Resultado, Inspecionou, Cotas medidas); autorizações (Data, OP, Ocorrência, Decisão, Crachá, Responsável, Motivo da recusa).
- Cards: Produção boa, Refugo, Retrabalho (backend `totals`, com ExplainableValue só se > 0); FTT (backend `ftt`, mesma fonte do OEE/Visão Geral).
- Cálculo no frontend: nenhum KPI novo. Só formatação e regex para "não informado" (`:563`).
- Exportação: não encontrado.
- Permissão: menu sem nível; backend `require_management_user`.
- Vazio: `EmptyState` por seção (`:586`, `:653`, `:670`). Zero em peça fica texto simples (`:557`).
- Mesmo dado em outra tela: FTT vem de `get_overview` (mesma fonte de OEE e Visão Geral). Refugo por motivo também alimenta Melhoria Contínua (`ImprovementPage.tsx:20,34`). Cotas e RNC são outra tela (ver pendências).
- Destino proposto: 06 Produção boa/refugo/retrabalho; 07 Inspeções (primeira peça e autorizações); 11 para FTT; 21 para a autorização/decisão quando for RNC.
- Observação: o payload do backend tem `evidence` (lista de eventos, `industrial_analytics.py:~236`), que a tela não exibe. Pode ser o campo que a Auditoria precisa, e hoje só existe na API. A primeira peça tem uma seção aqui e também pode existir em Qualidade > SPC/RNC (não verificado).

### Análises > Tempo padrão — `/analises/tempo-padrao-real`
- Componente: `AnalyticsPages.tsx:676`
- O que responde: comparação entre tempo padrão estimado e tempo real por OP/operação, com desvio.
- Endpoints: `GET /api/v1/analytics/standard-vs-actual` → `analytics.py:24` (alias `tempo_padrao_x_real`) → `industrial_analytics.py:267` (`standard_vs_actual`), amostras em `:352` (`standard_time_samples`), produção em `:332`.
- Filtros: `useManagementFilters()`.
- Cards: Comparações (contagem de linhas), Tempo padrão acumulado, Tempo real acumulado, Desvio do padrão (%).
- Tabela "Desvios por OP/operação": OP (link), Operação, Produto, Recurso real, Peças boas, Padrão estimado, Tempo real, Desvio, Desvio %, Fonte.
- Cálculo no frontend: soma de `tempo_padrao_estimado_segundos` e `tempo_producao_real_segundos` só nas linhas com os dois (`AnalyticsPages.tsx:684-692`). Desvio % = `(real - padrão) / padrão * 100` (`:717-720`, repetido em `:719-720`). Esta conta NÃO está no backend.
- Exportação: não encontrado.
- Permissão: menu sem nível; backend como OEE.
- Vazio: "Não configurado" (sem tempo padrão) e "Dados insuficientes" (`:703-712`). Desvio só com padrão > 0 (`:717`).
- Mesmo dado em outra tela: mesmo endpoint em Melhoria Contínua ("Operações que passaram do tempo padrão", `ImprovementPage.tsx:21,38-45`). Ali o `desvio_segundos` vem do backend, então a soma e o desvio % do Análise não são os mesmos cálculos que a Melhoria usa.
- Destino proposto: 08 Tempo padrão×real.
- Observação: Desvio % é calculado no frontend (`AnalyticsPages.tsx:717-720`). A Auditoria precisa da mesma conta no backend, ou a tela nova terá número diferente da atual.

### Análises > Cronoanálise — `/analises/cronoanalise`
- Componente: `AnalyticsPages.tsx:750`
- O que responde: distribuição do tempo real por peça agrupada por produto, operação e recurso (média, mediana, mín., máx., desvio).
- Endpoints: `GET /api/v1/analytics/chronoanalysis` → `analytics.py:24` (alias `cronoanalise`) → `industrial_analytics.py:399` (`chronoanalysis`), amostras em `:352`.
- Filtros: `useManagementFilters()`.
- Cards: Grupos analisados, Ciclo médio por peça, Maior variação, Ciclo mais lento.
- Tabela "Amostras": Produto, Operação, Recurso, Amostra, Média, Mediana, Mínimo, Máximo, Desvio. Gráfico "Média real por peça" (10 primeiros).
- Cálculo no frontend: média ponderada geral `Σ(média × amostras) / Σ amostras` (`AnalyticsPages.tsx:760-762`); "mais lento" e "mais variável" por ordenação (`:763-764`); total de amostras (`:759`). Esses números NÃO vêm do backend.
- Exportação: não encontrado.
- Permissão: menu sem nível; backend como OEE.
- Vazio: "Dados insuficientes" nos cards e no gráfico (`:770-775`).
- Mesmo dado em outra tela: `standard_time_samples` (`industrial_analytics.py:352`) também alimenta o Tempo padrão, pelo que li. Não verifiquei se Operações usa a mesma função.
- Destino proposto: 09 Cronoanálise.
- Observação: "Ciclo médio por peça" é uma média ponderada feita no frontend. Se a Auditoria exibir o mesmo número, precisa replicar esta conta ou mover para o backend.

### Análises > Capacidade — `/analises/capacidade-gargalos`
- Componente: `AnalyticsPages.tsx:798`
- O que responde: utilização do período, tempo disponível pelo calendário, capacidade livre, gargalo; tabela por recurso com tempo disponível, ocupado, livre, utilização, fila (OPs e horas), disputa.
- Endpoints: `GET /api/v1/analytics/capacity` → `analytics.py:24` (alias `capacidade`) → `industrial_analytics.py:627` (`capacity_configuration`). Dados: `self.db.listar_configuracao_capacidade_recursos` (`:645`), `self.db.listar_status_recursos` (`:610`), `CalendarService` (`:664`), `_queue_exceeds_free` (`:621`).
- Filtros: `useManagementFilters()`.
- Cards: Utilização do período (backend), Tempo disponível (backend total + explicação por soma), Capacidade livre (backend total + explicação por soma), Gargalo (backend).
- Colunas: Recurso, Setor, Tempo disponível, Tempo ocupado, Livre, Utilização, Fila, Fila (h) com aviso de "fila maior que o tempo livre" e "tempo estimado" e "sem tempo padrão", Disputa.
- Cálculo no frontend: explicação das somas de Tempo disponível e Capacidade livre é uma soma linha a linha no frontend (`AnalyticsPages.tsx:808-821`, uso em `:835` e `:846`). Contagem de fatos sem tempo padrão também somada no frontend (`:807`, `:890`).
- Exportação: não encontrado.
- Permissão: menu sem nível; backend como OEE.
- Vazio: "Não configurado" quando sem calendário; "Nenhum recurso no filtro" (`:866`).
- Mesmo dado em outra tela: não verificado (não li o serviço de calendário nem a Visão Geral).
- Destino proposto: 10 Capacidade e utilização.
- Observação: o total exibido vem do backend, mas a explicação é uma soma no frontend. Se as duas contas divergirem (ex.: recurso sem calendário), a explicação não bate com o cartão. Hoje o texto de nota cobre "recurso sem calendário" (`:818`).

### Análises > Confiabilidade — `/analises/confiabilidade`
- Componente: `AnalyticsPages.tsx:896`
- O que responde: MTBF, MTTR, quebras no período, equipamento mais crítico, quebras por equipamento (com MTTR), causas das quebras.
- Endpoints: `GET /api/v1/analytics/reliability` → `analytics.py:24` (alias `reliability`) → `industrial_analytics.py:477` (`reliability`), taxonomia em `:606` (`_stop_reason_catalog`). Há também `backend/api/routers/audit.py:81` com um `reliability` próprio. Não verifiquei se usa o mesmo serviço.
- Filtros: `useManagementFilters()`.
- Cards: MTBF (backend), MTTR (backend), Quebras no período (backend, com explicação por soma), Equipamento mais crítico (backend, primeiro de `por_recurso`).
- Tabela "Quebras por equipamento": Recurso, Quebras, Tempo parado, MTTR. Gráfico "Causas das quebras" (`motivos`).
- Cálculo no frontend: explicação da soma de quebras (`AnalyticsPages.tsx:906-914`). Valor do cartão é `data.falhas` (backend).
- Exportação: não encontrado.
- Permissão: menu sem nível; backend como OEE.
- Vazio: "Nenhuma quebra no período" e "Nenhuma causa registrada" com `reason` e `taxonomia` do backend (`:960`, `:965`).
- Mesmo dado em outra tela: `audit.py:81` tem outro endpoint `reliability` na API de Auditoria. Pode ser a mesma conta (não verificado).
- Destino proposto: 12 Falhas e confiabilidade (MTBF/MTTR).
- Observação: se Auditoria tiver seu próprio endpoint de confiabilidade (`audit.py:81`), há duas fontes para o mesmo indicador.

## Melhoria Contínua

### Melhoria Contínua > Oportunidades — `/melhoria-continua`
- Componente: `web/src/pages/improvement/ImprovementPage.tsx:17` (60 linhas). Não tem endpoint próprio.
- O que responde: três listas de onde a fábrica mais perde no período: maiores causas de parada (tempo), maiores motivos de refugo (peças), operações acima do tempo padrão (desvio).
- Endpoints (reaproveitados, sem nenhum novo):
  - `GET /api/v1/analytics/downtimes` (`:19`) → ver Paradas acima.
  - `GET /api/v1/analytics/quality` (`:20`) → ver Qualidade acima.
  - `GET /api/v1/analytics/standard-vs-actual` (`:21`) → ver Tempo padrão acima.
- Filtros: `useManagementFilters()`.
- Listas e títulos: "Maiores causas de parada (tempo parado)"; "Maiores motivos de refugo (N peças no período)" com total `quality.data.totals.refugo`; "Operações que passaram do tempo padrão" (desvio > 0, primeiras 8).
- Cálculo no frontend: ordenação e corte em 8 (`TOP`, `:10`, `:33`, `:36`, `:40`), filtro `desvio_segundos > 0` (`:39`), rótulo com OP/operação/produto (`:42`). Não recalcula valor.
- Exportação: não encontrado.
- Permissão: menu só admin ou atribuído `melhoria_continua` (`navigation.ts:298-310`); rota com `RequireImprovementAccess` (`App.tsx:138,213`). Backend: as três consultas exigem `require_management_user` (leitura comum, não restrito).
- Vazio/erro: "Sem paradas no período", "Sem refugo no período", "Nenhuma operação acima do padrão" (`:50-56`). Erro só mostrado se as três falharem (`:26`).
- Mesmo dado em outra tela: as três listas são as mesmas consultas das Análises (Paradas, Qualidade, Tempo padrão). Os números batem por construção, mas o corte (top 8) e a ordenação são só desta tela.
- Destino proposto: DASH (síntese de onde se perde), ou OPER se a tela continuar como lista de trabalho para a melhoria.
- Observação: a tela não tem campo que só exista nela; é uma reorganização das três análises. A "Operação acima do padrão" usa `desvio_segundos` do backend, diferente do desvio % calculado no frontend na aba Tempo padrão.

## Diretoria (parcial)

### Diretoria — `/diretoria` (abas Painel, Ficha, Custos)
- Componentes: `web/src/pages/director/DirectorPage.tsx:27` (abas e período, estado local); `DirectorPanel.tsx:12` (Painel); `DirectorSheet.tsx` (Ficha); `DirectorCosts.tsx` (Custos); `DirectorExplainable.tsx` (conta aberta por número).
- O que responde: Painel = produzido, horas paradas, custo das paradas, eficiência, onde mais perdemos, melhor e pior setor. Ficha = por setor ou recurso: trabalhou, produzido, parado, custo do trabalho, custo das paradas, paradas por motivo, quem operou. Custos = cadastro de custo/hora por recurso e por operador (editável).
- Filtros: período (`hoje`, `semana`, `mes`, `DirectorPage.tsx:16-20`), setor e recurso (Ficha, por clique em setor no Painel). Estado local, não vai pra URL.
- Endpoints:
  - `GET /diretoria/painel?periodo=` → `backend/api/routers/director.py:56` → `mes/services/director_summary.py:126` (`panel`).
  - `GET /diretoria/ficha?periodo=&setor=&recurso=` → `director.py:68` → `director_summary.py:177` (`sheet`).
  - `GET /diretoria/explicacao?metric=&periodo=...` → `director.py:82` → `mes/services/director_explanation.py` (474 linhas, não li).
  - `GET /diretoria/custos` → `director.py:102` → `director_summary.py:248` (`costs`): `listar_custos_hora_recurso`, `listar_custos_hora_operador`, `listar_operadores_apontamento`.
  - `PUT /diretoria/custos/recurso/{recurso}` (`director.py:107`) → `director_summary.py:283` → `db.salvar_custo_hora_recurso`. Exige `require_csrf`.
  - `PUT /diretoria/custos/pessoa/{operador_id}` (`director.py:127`) → `director_summary.py:289` → `db.salvar_custo_hora_operador`. Exige `require_csrf`.
  - `GET /diretoria/custos/auditoria` (`director.py:146`) → `mes/services/change_audit.py`.
  - Frontend: `web/src/api/client.ts:139-163` (`directorPaths`).
- Cards do Painel: Produzido (`cards.produzido` = `overview.production.good`), Horas paradas (`_unplanned_stop_hours`, `director_summary.py:520-525`: parada menos planejada do `overview.hours`), Custo das paradas (`stop_cost`, backend), Eficiência (`overview.kpis.oee`, backend).
- Cards da Ficha: Trabalhou, Produzido, Parado, Custo do trabalho, Custo das paradas (`DirectorSheet.tsx:70-86`), todos vindos de `sheet()`.
- Cálculo no frontend: nenhum KPI calculado. Só formatação (`directorFormat.ts`: `formatMoney`, `formatRate`, `parseRate`). Melhor e pior setor vêm prontos do backend (`best_and_worst_sector`, `director_summary.py:101-118`).
- Exportação: não encontrado em `pages/director/*` (busca de export ainda não feita no projeto todo).
- Permissão: menu e rota com `DIRECTOR_LEVELS`; backend `require_diretoria_user` no router inteiro (`director.py:42`) e nas gravações de custo. Custos: `set_resource_rate`/`set_operator_rate` exigem `require_diretoria_user`.
- Vazio/erro: Painel sem dado = `LoadingState` ou `ErrorState` (`DirectorPanel.tsx:15-17`). Sem paradas = EmptyState "Sem paradas no período" (`:97`). Custos ausentes: texto "Sem custo cadastrado" (`directorFormat.ts:6`) e aviso "faltam custos de N recursos/pessoas — o valor real é maior" (`director_summary.py:95-96`). Custo parcial é marcado por `custo_completo`.
- Mesmo dado em outra tela:
  - Eficiência = `kpis.oee` de `get_overview` (mesma da Análises > OEE e Visão Geral).
  - Horas paradas usa `overview.hours`, mas Análises > Paradas usa `paradas_tela` (`physical_consolidation`). Mesmo conceito, caminhos diferentes. Não comparei se o número é igual.
  - Parada usa `analytics.downtimes` (mesma lista de Análises > Paradas e de Melhoria).
- Destino proposto: DASH (Painel). Ficha: 04/05 para eventos, 08/11 para o cálculo. Custos (edição de taxa): OPER.
- Observação (risco): o custo das paradas e do trabalho é calculado só nesta tela, com taxa por hora cadastrada (`listar_custos_hora_*`). Nenhuma outra tela mostra custo. Se a Auditoria precisar de R$, precisa usar o mesmo `stop_cost` e o mesmo cadastro, e exige permissão de diretoria (`require_diretoria_user`). Campos de custo só existem aqui.

## Qualidade (menu Qualidade: Cotas padrão, SPC, Decisão de RNC)

Menu: `web/src/config/navigation.ts:269-283`. Guarda: `RequireQualityTemplateAccess` (`web/src/App.tsx:125`, rotas 207-209). Níveis: admin, desenvolvedor e `qualidade`. Backend: `require_qualidade_user` nas rotas de Qualidade.

### Qualidade > Cotas padrão — `/qualidade/cotas`
- Componente: `web/src/pages/production/QualityTemplatesPage.tsx` (350 linhas; só li rótulos e paginação).
- O que responde: cotas padrão (medidas esperadas) por produto, com filtros e paginação.
- Endpoints: `GET /api/v1/management/quality-templates` (`backend/api/routers/management.py:1017`, `limit`/`offset`, `require_qualidade_user`) → `database.listar_templates_qualidade`. Também `GET /api/v1/quality/templates/{produto}` (`backend/api/routers/quality.py:236`) e `POST /api/v1/quality/templates` (`quality.py:257`, escrita com CSRF).
- Filtros: produto (`produto`, máx. 60). Paginação: `limit` e `offset`.
- Cálculo no frontend: só paginação (`QualityTemplatesPage.tsx:237`, `Math.max`).
- Exportação: não encontrado.
- Permissão: menu e rota `QUALITY_TEMPLATE_LEVELS`; backend `require_qualidade_user`. Escrita também exige `require_csrf`.
- Vazio/erro: "Produtos com cotas padrão" (`:143`). Estados completos não li.
- Mesmo dado em outra tela: não verificado.
- Destino proposto: OPER (cadastro).

### Qualidade > SPC — `/qualidade/spc`
- Componente: `web/src/pages/production/QualitySpcPage.tsx` (217 linhas). Somente leitura.
- O que responde: cartas de controle (X e dispersão) e Cpk por cota, dentro da OP/lote (não capacidade de máquina).
- Endpoint: `GET /api/v1/quality/spc` (`backend/api/routers/quality.py:320`, `require_qualidade_user`). Parâmetros: `product`, `cota`, `start`, `end`. Corte de linhas com flag `truncado`. Dados: `database.listar_medidas_spc`. Cálculo: `mes/services/quality_spc.py:343` (`analisar_medicoes`), no backend.
- Filtros: produto, cota, início, fim (`QualitySpcPage.tsx:150`).
- Campos: Cpk e limites LIC/LSC (`QualitySpcPage.tsx:88-110`), média (`:52`), limites da carta X e dispersão (`:57`, `:75`). Números vêm do backend; não encontrei aritmética no arquivo.
- Exportação: não encontrado.
- Vazio: "Sem medições suficientes" (`:201`). Backend não dá limites nem Cpk com amostra curta (menos de 20 medidas ou menos de 5 subgrupos).
- Mesmo dado em outra tela: "Cotas medidas" aparece como texto em Análises > Qualidade > Primeira peça (`AnalyticsPages.tsx:650`, campo `observacao`). Não é o mesmo cálculo.
- Destino proposto: 07 Inspeções e medições.
- Observação: com `truncado`, medições antigas somem da carta. Não verifiquei se a tela avisa isso.

### Qualidade > Decisão de RNC — `/qualidade/rnc`
- Componente: `web/src/pages/production/QualityRncDecisionPage.tsx` (225 linhas).
- O que responde: lista de RNCs (não conformidades) com a decisão vigente e formulário para registrar decisão.
- Endpoints:
  - Leitura: `GET /api/v1/quality/rnc` (`backend/api/routers/quality.py:362`, `limite` 1 a 200, `somente_sem_decisao`) → `mes/services/quality_rnc_decision.py:154` (`listar_pendencias`).
  - Leitura: `GET /api/v1/quality/rnc/{rnc_id}/decisions` (`quality.py:423`).
  - ESCRITA: `POST /api/v1/quality/rnc/{rnc_id}/decisions` (`quality.py:380`, com `require_csrf`).
- Filtros: "Quais RNCs mostrar" (`QualityRncDecisionPage.tsx:153`), `somente_sem_decisao`.
- Campos: formulário "Registrar decisão da RNC" (`:195`), "Histórico de decisões" (`:73`).
- Cálculo no frontend: nenhum.
- Exportação: não encontrado.
- Permissão: menu e rota de Qualidade; backend `require_qualidade_user` na leitura e na escrita.
- Vazio/erro: estados não li.
- Mesmo dado em outra tela: RNC e decisão não aparecem em Análises (não encontrado).
- Destino proposto: 21 RNC e decisões. OPER (grava dado).
- Observação (risco): é a única tela desta lista que grava dado de decisão. Não tratar como leitura na Auditoria.

## Primeira peça (seção de Análises > Qualidade)
- Endpoint: `GET /api/v1/management/first-pieces` → `backend/api/routers/management.py:886` (`first_pieces`). Parâmetros: `sector`, `status`, `blocked_only`. Guarda `require_management_user`. Dados: `database.listar_primeiras_pecas` (definição não localizada em `backend` nem `mes`; SQL não verificado).
- Consumidor: `AnalyticsPages.tsx:629`.

## Exportação (busca global)
- XLSX/CSV existe só em Relatórios: `backend/api/routers/reports.py:227` (`/{report_type}/export.csv`) e `:254` (`/{report_type}/export.xlsx`). Frontend: `web/src/pages/reports/ReportsPages.tsx` (`DownloadAction`), `web/src/api/client.ts:106` (`download()`).
- Produção realizada (`web/src/pages/production/ProductionPages.tsx:112`) usa `DownloadAction type="producao"`. Não é tela desta lista.
- Nenhuma tela de Análises, Diretoria, Melhoria Contínua ou Qualidade (cotas, SPC, RNC) tem exportação. Busca em `AnalyticsPages.tsx`, `pages/director/*`, `pages/improvement/*` e as três páginas de Qualidade: sem match de export, download, csv ou xlsx.
- Há teste `test_report_xlsx_matches_screen.py` que liga o XLSX de Relatórios aos totais da tela de Produção. Não se aplica às telas desta lista.

## Riscos para a decisão
1. Três "Utilização" com fontes diferentes: Horas (simulação, bloco `tempos` do `frontend_facade`), OEE (`extended_metrics.utilization`), Capacidade ("Utilização do período", `capacity_configuration`).
2. FTT aparece em OEE (`kpis` de `inicio`) e em Qualidade (`quality()` → `get_overview.kpis.ftt`). Mesma fonte, dois endpoints.
3. Eficiência (Diretoria) = `kpis.oee` = OEE (Análises). Mesmo indicador.
4. "Horas paradas" (Diretoria, `overview.hours`) × "Parada não planejada" (Análises > Paradas, `physical_consolidation`). Caminhos diferentes; números não comparados.
5. Cálculo no frontend: Desvio % do Tempo padrão (`AnalyticsPages.tsx:717-720`); média ponderada da Cronoanálise (`:760-762`); soma de tempo disponível e livre na Capacidade (`:808-821`). Melhoria usa `desvio_segundos` do backend.
6. Custo em R$ (Custo das paradas, Custo do trabalho) só existe na Diretoria, com taxa cadastrada (`listar_custos_hora_*`) e `require_diretoria_user`.
7. `evidence` no payload de Qualidade (`industrial_analytics.py`, em torno da linha 236) não é exibido.
8. `backend/api/routers/audit.py:81` tem outro endpoint `reliability`. Não verifiquei se é a mesma conta de `analytics/reliability`.
9. Paradas e Setup são uma rota só (`/analises/paradas`); a aba não entra na URL.
10. Melhoria Contínua não tem endpoint próprio: depende de três análises.

## Pendências
- Não li por inteiro: `QualityTemplatesPage.tsx`, `QualityRncDecisionPage.tsx`, `mes/services/director_explanation.py`, e estados de erro/vazio de Cotas e RNC.
- SQL não rastreado: `listar_primeiras_pecas`, `listar_medidas_spc`, `listar_templates_qualidade`, e as tabelas/views de cada `listar_*` citado.
- Não verifiquei se `audit.py:81` é a mesma conta de `analytics/reliability`.
- Não comparei numericamente "Horas paradas" (Diretoria) com "Parada não planejada" (Paradas).


# Anexo — inv_B_part2

## Qualidade (menu Qualidade: Cotas padrão, SPC, Decisão de RNC)

Menu: `web/src/config/navigation.ts:269-283`. Guarda: `RequireQualityTemplateAccess` (`web/src/App.tsx:125`, rotas 207-209). Níveis: admin, desenvolvedor e `qualidade`. Backend: `require_qualidade_user` nas rotas de Qualidade.

### Qualidade > Cotas padrão — `/qualidade/cotas`
- Componente: `web/src/pages/production/QualityTemplatesPage.tsx` (350 linhas; só li rótulos e paginação).
- O que responde: cotas padrão (medidas esperadas) por produto, com filtros e paginação.
- Endpoints: `GET /api/v1/management/quality-templates` (`backend/api/routers/management.py:1017`, `limit`/`offset`, `require_qualidade_user`) → `database.listar_templates_qualidade`. Também `GET /api/v1/quality/templates/{produto}` (`backend/api/routers/quality.py:236`) e `POST /api/v1/quality/templates` (`quality.py:257`, escrita com CSRF).
- Filtros: produto (`produto`, máx. 60). Paginação: `limit` e `offset`.
- Cálculo no frontend: só paginação (`QualityTemplatesPage.tsx:237`, `Math.max`).
- Exportação: não encontrado.
- Permissão: menu e rota `QUALITY_TEMPLATE_LEVELS`; backend `require_qualidade_user`. Escrita também exige `require_csrf`.
- Vazio/erro: "Produtos com cotas padrão" (`:143`). Estados completos não li.
- Mesmo dado em outra tela: não verificado.
- Destino proposto: OPER (cadastro).

### Qualidade > SPC — `/qualidade/spc`
- Componente: `web/src/pages/production/QualitySpcPage.tsx` (217 linhas). Somente leitura.
- O que responde: cartas de controle (X e dispersão) e Cpk por cota, dentro da OP/lote (não capacidade de máquina).
- Endpoint: `GET /api/v1/quality/spc` (`backend/api/routers/quality.py:320`, `require_qualidade_user`). Parâmetros: `product`, `cota`, `start`, `end`. Corte de linhas com flag `truncado`. Dados: `database.listar_medidas_spc`. Cálculo: `mes/services/quality_spc.py:343` (`analisar_medicoes`), no backend.
- Filtros: produto, cota, início, fim (`QualitySpcPage.tsx:150`).
- Campos: Cpk e limites LIC/LSC (`QualitySpcPage.tsx:88-110`), média (`:52`), limites da carta X e dispersão (`:57`, `:75`). Números vêm do backend; não encontrei aritmética no arquivo.
- Exportação: não encontrado.
- Vazio: "Sem medições suficientes" (`:201`). Backend não dá limites nem Cpk com amostra curta (menos de 20 medidas ou menos de 5 subgrupos).
- Mesmo dado em outra tela: "Cotas medidas" aparece como texto em Análises > Qualidade > Primeira peça (`AnalyticsPages.tsx:650`, campo `observacao`). Não é o mesmo cálculo.
- Destino proposto: 07 Inspeções e medições.
- Observação: com `truncado`, medições antigas somem da carta. Não verifiquei se a tela avisa isso.

### Qualidade > Decisão de RNC — `/qualidade/rnc`
- Componente: `web/src/pages/production/QualityRncDecisionPage.tsx` (225 linhas).
- O que responde: lista de RNCs (não conformidades) com a decisão vigente e formulário para registrar decisão.
- Endpoints:
  - Leitura: `GET /api/v1/quality/rnc` (`backend/api/routers/quality.py:362`, `limite` 1 a 200, `somente_sem_decisao`) → `mes/services/quality_rnc_decision.py:154` (`listar_pendencias`).
  - Leitura: `GET /api/v1/quality/rnc/{rnc_id}/decisions` (`quality.py:423`).
  - ESCRITA: `POST /api/v1/quality/rnc/{rnc_id}/decisions` (`quality.py:380`, com `require_csrf`).
- Filtros: "Quais RNCs mostrar" (`QualityRncDecisionPage.tsx:153`), `somente_sem_decisao`.
- Campos: formulário "Registrar decisão da RNC" (`:195`), "Histórico de decisões" (`:73`).
- Cálculo no frontend: nenhum.
- Exportação: não encontrado.
- Permissão: menu e rota de Qualidade; backend `require_qualidade_user` na leitura e na escrita.
- Vazio/erro: estados não li.
- Mesmo dado em outra tela: RNC e decisão não aparecem em Análises (não encontrado).
- Destino proposto: 21 RNC e decisões. OPER (grava dado).
- Observação (risco): é a única tela desta lista que grava dado de decisão. Não tratar como leitura na Auditoria.

## Primeira peça (seção de Análises > Qualidade)
- Endpoint: `GET /api/v1/management/first-pieces` → `backend/api/routers/management.py:886` (`first_pieces`). Parâmetros: `sector`, `status`, `blocked_only`. Guarda `require_management_user`. Dados: `database.listar_primeiras_pecas` (definição não localizada em `backend` nem `mes`; SQL não verificado).
- Consumidor: `AnalyticsPages.tsx:629`.

## Exportação (busca global)
- XLSX/CSV existe só em Relatórios: `backend/api/routers/reports.py:227` (`/{report_type}/export.csv`) e `:254` (`/{report_type}/export.xlsx`). Frontend: `web/src/pages/reports/ReportsPages.tsx` (`DownloadAction`), `web/src/api/client.ts:106` (`download()`).
- Produção realizada (`web/src/pages/production/ProductionPages.tsx:112`) usa `DownloadAction type="producao"`. Não é tela desta lista.
- Nenhuma tela de Análises, Diretoria, Melhoria Contínua ou Qualidade (cotas, SPC, RNC) tem exportação. Busca em `AnalyticsPages.tsx`, `pages/director/*`, `pages/improvement/*` e as três páginas de Qualidade: sem match de export, download, csv ou xlsx.
- Há teste `test_report_xlsx_matches_screen.py` que liga o XLSX de Relatórios aos totais da tela de Produção. Não se aplica às telas desta lista.

## Riscos para a decisão
1. Três "Utilização" com fontes diferentes: Horas (simulação, bloco `tempos` do `frontend_facade`), OEE (`extended_metrics.utilization`), Capacidade ("Utilização do período", `capacity_configuration`).
2. FTT aparece em OEE (`kpis` de `inicio`) e em Qualidade (`quality()` → `get_overview.kpis.ftt`). Mesma fonte, dois endpoints.
3. Eficiência (Diretoria) = `kpis.oee` = OEE (Análises). Mesmo indicador.
4. "Horas paradas" (Diretoria, `overview.hours`) × "Parada não planejada" (Análises > Paradas, `physical_consolidation`). Caminhos diferentes; números não comparados.
5. Cálculo no frontend: Desvio % do Tempo padrão (`AnalyticsPages.tsx:717-720`); média ponderada da Cronoanálise (`:760-762`); soma de tempo disponível e livre na Capacidade (`:808-821`). Melhoria usa `desvio_segundos` do backend.
6. Custo em R$ (Custo das paradas, Custo do trabalho) só existe na Diretoria, com taxa cadastrada (`listar_custos_hora_*`) e `require_diretoria_user`.
7. `evidence` no payload de Qualidade (`industrial_analytics.py`, em torno da linha 236) não é exibido.
8. `backend/api/routers/audit.py:81` tem outro endpoint `reliability`. Não verifiquei se é a mesma conta de `analytics/reliability`.
9. Paradas e Setup são uma rota só (`/analises/paradas`); a aba não entra na URL.
10. Melhoria Contínua não tem endpoint próprio: depende de três análises.

## Pendências
- Não li por inteiro: `QualityTemplatesPage.tsx`, `QualityRncDecisionPage.tsx`, `mes/services/director_explanation.py`, e estados de erro/vazio de Cotas e RNC.
- SQL não rastreado: `listar_primeiras_pecas`, `listar_medidas_spc`, `listar_templates_qualidade`, e as tabelas/views de cada `listar_*` citado.
- Não verifiquei se `audit.py:81` é a mesma conta de `analytics/reliability`.
- Não comparei numericamente "Horas paradas" (Diretoria) com "Parada não planejada" (Paradas).


# Anexo — inv_C_dev_paineis

# Inventário: IagoDev, Tela inicial, Painéis, Áreas (somente leitura)

Status: parcial. Telas em formato completo: 6. Telas em formato resumido: 9. Rotas órfãs: lista no fim. Itens marcados "não verificado" ainda não foram conferidos no código.

## Formato completo

### IagoDev > Alterações — `/inicio/alteracoes`
- Componente: `web/src/pages/home/ChangeAuditPage.tsx:109`
- O que responde: quem criou, alterou ou excluiu usuário, nível, turno, pausa, decisão de RNC, sugestão de manutenção, etc. Uma linha = um registro de auditoria.
- Endpoints: `GET /api/v1/management/audit` → `backend/api/routers/management.py:742` (`list_audit`) → consulta em `management.py` (função `consultar`) → tabela `auditoria_alteracoes`. `POST /api/v1/management/audit/{id}/undo` → `management.py:779` (`undo_audit`) → tabela `auditoria_alteracoes` e tabela da entidade desfeita.
- Filtros: O quê (padrão Tudo), Quem (texto ou id, opcional), De e Até (datas, opcionais). Limite fixo de 200 no frontend; backend padrão 100, máximo 500.
- Colunas: Quando, Quem, O quê (entidade · chave), Ação, Mudança (campo: antes → depois), botão Desfazer (só desenvolvedor).
- Cards/KPIs: nenhum. Só o contador "N alteração(ões)" vindo de `data.count`.
- Exportação: não encontrado.
- Permissão: menu `adminOnly` (`web/src/config/navigation.ts:316`, aba na linha 331). Rota com `RequireAdmin` (`App.tsx:188`). Backend: listar exige `require_admin_user`; desfazer exige `require_developer_user` + CSRF (`management.py:782`). Frontend e backend batem.
- Estados: carregando mostra LoadingState. Erro 403 mostra "exclusiva da conta de administração"; outro erro mostra botão Tentar novamente. Vazio mostra "Nenhuma alteração registrada para este filtro." Zero e erro são distinguidos.
- Mesmo dado em outra tela: valores em R$ ficam em `/diretoria/custos/auditoria` (`backend/api/routers/director.py:146`), fora desta tela (comentário em `management.py:746`).
- Destino proposto: 17. Sem DASH.
- Observação: Desfazer é ação de escrita dentro da consulta, com confirmação. A trava de quem pode ver o botão está no frontend e no backend. Os campos antes/depois trazem nomes de usuário, níveis e horários (dado pessoal).

### IagoDev > Envios ao Protheus — `/inicio/envios-protheus`
- Componente: `web/src/pages/home/TotvsOutboxPage.tsx:46`
- O que responde: envios que o Protheus recusou (apontamento de início, apontamento, encerramento de OP). Uma linha = um envio da fila de integração.
- Endpoints:
  - `GET /api/v1/admin/totvs-outbox?status=` → `backend/api/routers/totvs_outbox.py:54` (`list_items`, `require_admin_user`) → `mes/services/totvs_outbox_admin.py:43` → `app/database/totvs_outbox_repository.py:584` → tabela `totvs_outbox`.
  - `POST /api/v1/admin/totvs-outbox/{id}/reprocess` → `totvs_outbox.py:65` (`require_admin_user` + CSRF) → `totvs_outbox_admin.py:~62` (`reprocess`) → `reprocessar_item_outbound_totvs` (`totvs_outbox_repository.py:443`) ou `_rebuild_blocked` → `totvs_outbox`. Volta o item para PENDING; o worker `gestor-totvs-outbox-worker` (`backend/api/main.py:756`) envia de novo ao Protheus.
  - `POST /api/v1/admin/totvs-outbox/{id}/discard` → `totvs_outbox.py:76` (corpo `motivo`, mínimo 3 letras) → `totvs_outbox_admin.py:52` → `descartar_item_outbound_totvs` (`totvs_outbox_repository.py:478`) → `totvs_outbox`.
  - Tentativas (`totvs_outbox_attempts`) existem no serviço, mas não aparecem na tela.
- Filtros: Situação (padrão Com erro = ERROR; opções Descartados e Todos).
- Colunas: Envio (id), OP, Tipo (evento + operação), Situação, Última mudança, O que o Protheus respondeu (`last_error_message`, ou "Descartado por X: motivo"), Ações.
- Ações (só na linha com status ERROR): Reenviar (sem confirmação) e Descartar (motivo digitado em `window.prompt`, sem confirmação extra).
- Cards/KPIs: nenhum. `metricas()` existe no serviço (`totvs_outbox_admin.py:40`), não vi uso na tela.
- Exportação: não encontrado.
- Permissão: menu `adminOnly` (`navigation.ts:332`). Rota `RequireAdmin` (`App.tsx:189`). Backend: `require_admin_user` nas 3 rotas. Não exige desenvolvedor.
- Estados: carregando; erro 403 "exclusiva da administração"; outro erro com Tentar novamente; vazio "Nenhum envio nesta situação."; erro de ação aparece em Notice.
- Mesmo dado em outra tela: as ações entram no Log do Sistema, área "protheus" (`backend/observability/system_log.py:63`).
- Destino proposto: 19 + OPER (é tela de execução: reenviar e descartar).
- Observação: Reenviar dispara um novo envio real ao Protheus, sem confirmação. Quando o payload faltava, o sistema remonta a mensagem a partir do fato canônico. Descartar é irreversível e não tem desfazer. O comentário do serviço (`totvs_outbox_admin.py:3`, "Não existe UI nova nesta etapa") está desatualizado.

### IagoDev > Log do Sistema — `/inicio/log-sistema`
- Componente: `web/src/pages/home/SystemLogPage.tsx:32`
- O que responde: o que mudou ou falhou no sistema, por área (ações de usuários, erros, integrações, serviços). Uma linha = um evento. A própria tela diz que leituras normais não entram e que a retenção é de 30 dias.
- Endpoints:
  - `GET /api/v1/management/system-log` → `management.py:842` (`system_log`, `require_admin_user`) → `database.listar_log` → tabela `log_sistema`.
  - `GET /api/v1/management/system-log/summary?horas=24` → `management.py:864` (`require_admin_user`) → `database.resumo_log` → tabela `log_sistema`.
- Filtros: Área (botões; padrão Todas), Nível (Todos, Informação, Aviso, Erro), Texto (até 120 caracteres; mensagem, rota ou evento), Quem (até 80), De e Até (datas), "Atualizar sozinho (10 s)" (ligado por padrão).
- Colunas: Quando, Nível, Área (rótulo do resumo ou id bruto), Quem, O que aconteceu (mensagem; ao expandir: evento, rota, método, status HTTP, duração, request_id, detalhe em JSON).
- Cards/KPIs: botões de área com total e erros das últimas 24 h. Calculado no backend (`management.py:864-883`), só exibido no frontend.
- Exportação: não encontrado.
- Permissão: menu `adminOnly` (`navigation.ts:333`). Rota `RequireAdmin` (`App.tsx:190`). Backend: `require_admin_user` nas duas rotas.
- Estados: erro da lista mostra mensagem e Tentar novamente. Vazio "Nenhum registro para este filtro." Erro do resumo não tem tratamento: `summary.data?.areas ?? []` esconde os botões de área sem aviso.
- Mesmo dado em outra tela: área "protheus" vem de `system_log.py:63`, ligada à tela de Envios.
- Destino proposto: 18. Resumo de erros 24 h pode ir a DASH (sugestão, não decidido).
- Observação: os campos `mensagem` e `detalhe` (JSON) podem trazer dados do sistema; não verifiquei o que é gravado. Coluna Quem traz nome de usuário. Auto-atualização a cada 10 s faz 2 chamadas por ciclo.

### Tela inicial > Chamadas da Gestão — `/inicio/chamadas`
- Componente: `web/src/pages/home/ChamadasPage.tsx:66` (`ManagementChamadasPage`)
- O que responde: histórico de chamadas feitas por operador e gestão, com quem foi chamado, motivo, prioridade e se o aviso chegou. Uma linha = uma chamada.
- Endpoints: `GET /api/v1/chamadas/admin/historico` → `backend/api/routers/chamadas.py:416` (`require_management_user`) → `app/database/chamada_repository.py:244` (`listar_chamadas`, limite 200, `SELECT *`) → tabela `chamadas`. `_publica` (`chamadas.py:101`) remove `contato_telegram_chat_id` e acrescenta `telegram_status`.
- Filtros: nenhum. Limite fixo de 200 (texto "Últimas 200" escrito na tela).
- Colunas: Quando, Para (contato e função), Motivo, Prioridade, Comentário, Solicitado por (nome, crachá, e-mail), Aviso (Enviado, Falhou, Enviando…, Sem confirmação, Na tela dele(a), Atendida).
- Cards/KPIs:
  - Chamadas registradas: tamanho da lista (frontend, `ChamadasPage.tsx:96`).
  - Sem aviso no Telegram: conta Falhou e Sem confirmação (frontend, `ChamadasPage.tsx:88-91`).
  - "Sem confirmação" = pendente há mais de 5 min, usando o relógio do navegador (frontend, `ChamadasPage.tsx:58`).
- Exportação: não encontrado.
- Permissão: menu sem `adminOnly` (`navigation.ts:170`). Rota sem guarda extra (`App.tsx:184`). Backend: qualquer conta de gestão. Coerente com a intenção declarada no código.
- Estados: carregando; erro sem dado mostra ErrorState (não distingue 403); vazio "Nenhuma chamada registrada ainda".
- Mesmo dado em outra tela: mesma tabela `chamadas` usada pelo sininho (`chamadas.py:397-416`, não verificado em detalhe). Cadastro de contatos fica em Chamadas do IagoDev.
- Destino proposto: 20. O KPI "Sem aviso no Telegram" é candidato a DASH.
- Observação: qualquer conta de gestão vê e-mail e crachá de quem chamou (dado pessoal). Cálculo de estado do aviso fica no frontend. Texto de erro do Telegram vai em tooltip; não verifiquei se contém token (o comentário diz que não).

### IagoDev > Chamadas do IagoDev — `/inicio/chamadas-dev`
- Componente: `web/src/pages/home/ChamadasContatosPage.tsx:46` (`DevChamadasContatosPage`)
- O que responde: cadastro de quem recebe chamadas (nome, função, ativo, padrão da gestão, conta do sistema, ID do Telegram, setores). Uma linha = um contato.
- Endpoints:
  - `GET /api/v1/chamadas/admin/contatos` → `chamadas.py:340` (`require_admin_user`) → `chamada_repository.py:12` com `completo=True` → tabela `chamada_contatos` (inclui `telegram_chat_id`).
  - `GET /api/v1/chamadas/admin/contas` → `chamadas.py:371` (`require_admin_user`) → `listar_usuarios()` → tabela `usuarios`.
  - `GET /api/v1/chamadas/setores` → `chamadas.py:159` (`get_current_user`) → lista de setores (sem tabela).
  - `POST /api/v1/chamadas/admin/contatos` → `chamadas.py:349` (`require_admin_user` + CSRF). Serve para criar, editar, ativar, desativar e tornar padrão.
  - `DELETE /api/v1/chamadas/admin/contatos/{id}` → `chamadas.py:386` (`require_admin_user` + CSRF) → `remover_chamada_contato` → tabela `chamada_contatos`.
- Filtros: Situação (Ativo, Inativo) e Busca (nome ou função). Filtro feito no frontend.
- Colunas: Nome, Função, Situação, Padrão da gestão, Recebe na tela de (conta), Telegram (Configurado, Não usa, Usa o chat geral), Setores, Ações.
- Cards/KPIs: Contatos ativos e Sem contato cadastrado (Sim/Não). Calculados no frontend (`ChamadasContatosPage.tsx:125, 142`).
- Exportação: não encontrado.
- Permissão: menu `adminOnly` (`navigation.ts:328`). Rota `RequireAdmin` (`App.tsx:185`). Backend: `require_admin_user` nas rotas de admin. O dropdown do operador (`GET /chamadas/contatos`) não traz Telegram.
- Estados: carregando; erro sem dado mostra ErrorState; vazio "Nenhum contato cadastrado ainda". Erro ao salvar mostra texto genérico "Confira o nome e a função" (`ChamadasContatosPage.tsx:90-91`), o motivo real some. Erro ao remover também é genérico.
- Mesmo dado em outra tela: `chamada_contatos` alimenta o dropdown do operador e o histórico (`chamadas.py:142`). O endpoint de contas é o mesmo usado no cadastro de usuários.
- Destino proposto: OPER (cadastro).
- Observação: "Remover" é permanente (confirmação avisa que não pode ser desfeita). "Desativar" pede confirmação. "Tornar padrão da gestão" não pede confirmação. O ID do Telegram é dado de contato pessoal e só o admin lê.

### Tela inicial > IA — `/inicio/ia`
- Componente: `web/src/pages/AIPage.tsx:158` (`AIPage`). Cliente: `web/src/api/ai.ts`.
- O que responde: chat com a IA sobre dados do MES (fábrica, setor, OP, KPI, perdas, relatórios). A IA não executa ações produtivas (texto da tela). Uma linha = uma mensagem da conversa.
- Endpoints:
  - `GET /api/v1/ai/status` → `backend/api/routers/ai.py:64` (`require_management_user`).
  - `GET /api/v1/ai/conversations` → `ai.py:75`. `POST` → `ai.py:83` (CSRF).
  - `GET /api/v1/ai/conversations/{id}` → `ai.py:93`. `DELETE` → `ai.py:105` (CSRF, 204).
  - `POST /api/v1/ai/conversations/{id}/messages` → `ai.py:119` (resposta em streaming, CSRF). Chama provedor externo compatível com OpenAI (`backend/ai/openai_compatible_provider.py`). Tabelas: `ai_conversations`, `ai_messages`, `ai_knowledge`.
  - `POST /api/v1/reports/artifacts/{id}/send` → `backend/api/routers/reports.py:101` (`require_management_user` + CSRF). Envia arquivo ao Telegram.
  - Download dos arquivos: `reports.py:121` (`/artifacts/{id}/download`).
- Filtros: nenhum. Conversas agrupadas por data.
- Colunas: n/a (chat).
- Cards/KPIs: nenhum.
- Exportação: links "Export técnico" e "Export simples" (download da API) e "Enviar pelo Telegram" por arquivo (`AIPage.tsx:86, 106-111`).
- Permissão: menu Tela inicial sem `adminOnly` (`navigation.ts:167`). Rota sem guarda extra (`App.tsx:193`). Backend: `require_management_user` em todas as rotas de IA. Dono da conversa checado no serviço (não verificado).
- Estados: "Verificando a IA…" enquanto carrega; IA desabilitada ou sem configuração mostra EmptyState; limite de uso mostra contagem regressiva; pergunta grande demais tem mensagem própria; erro genérico com Tentar novamente.
- Mesmo dado em outra tela: explicação de KPI usa `/management/kpis/{kpi}/explanation` (`management.py:129`). Dev Observatory tem rotas `/ai/*` (`dev_observatory.py:648-766`), não verificado se são a mesma IA.
- Destino proposto: fora do catálogo 01–21 (ferramenta de consulta, não relatório). Sem DASH e sem OPER.
- Observação: perguntas e possivelmente dados do MES vão a um provedor externo. Não verifiquei quais campos entram no contexto. Envio de arquivo ao Telegram sai do sistema.

## Formato resumido

### Painéis Operacionais > Andon — `/inicio/andon` (redireciona para `/andon`)
- Componente: `web/src/pages/AndonPage.tsx:293`. Redirect em `App.tsx:180` e `App.tsx:166`.
- Endpoints: `GET /api/v1/andon` → `backend/api/routers/andon.py:15` (`require_andon_user`) → fachada de frontend (não rastreada até a tabela).
- Permissão: a guarda da rota (`App.tsx:72`) deixa passar gestão sem `andon_access`, mas `require_andon_user` (`backend/api/dependencies/auth.py:307`) só aceita `andon_access`. Pelo código, gestão sem Andon recebe 403 na tela.
- Destino proposto: OPER (painel de chão). Indicadores podem ir a DASH.

### Painéis Operacionais > Mapa da fábrica — `/inicio/mapa-fabrica` (redireciona para `/mapa-fabrica`)
- Componente: mesmo `AndonPage.tsx:293` com `mapOnly`. Rota `App.tsx:167` com `RequireAuth management`.
- Endpoints: `GET /api/v1/andon` (mesmo do Andon).
- Destino proposto: OPER.

### Painéis Operacionais > Pausas — `/inicio/pausas`
- Componente: `web/src/pages/home/PausesPage.tsx:82`.
- Endpoints: `GET /api/v1/management/pauses` (`management.py:167`, `require_management_user` + escopo por setor `_require_pause_scope`, `management.py:162`); `POST` (`management.py:185`, CSRF); `DELETE /pauses/{id}` (`management.py:220`, CSRF). Tabela `pausas_automaticas_setor`.
- Destino proposto: OPER.
- Observação: qualquer gestão cria e exclui pausas, limitado pelo escopo do setor. Remover pede confirmação (`PausesPage.tsx:268`).

### IagoDev > Crachás — `/inicio/crachas`
- Componente: `web/src/pages/home/BadgesPage.tsx:86`. Rota `RequireAdmin` (`App.tsx:183`).
- Endpoints: `GET /api/v1/management/badges` (`management.py:384`, `require_admin_user`); `POST /badges` (`management.py:409`, admin + CSRF); `POST /badges/{id}/telegram-link-code` (`management.py:442`, admin); `DELETE /badges/{id}/telegram-link` (`management.py:467`, admin). Tabela `operadores_apontamento` (não confirmada para esta rota).
- Destino proposto: OPER.
- Observação: crachá identifica o operador (dado pessoal). Vincula conta do Telegram.

### IagoDev > Cadastro — `/inicio/cadastro`
- Componente: `web/src/pages/home/UsersPage.tsx:78`. Rota `RequireAdmin` (`App.tsx:192`).
- Endpoints: `GET /api/v1/management/users` (`management.py:571`, admin); `POST /users` (`management.py:641`, admin + CSRF); `DELETE /users/{id}` (`management.py:720`, admin + CSRF); `POST /levels` (`management.py:593`, admin + CSRF); `DELETE /levels/{nome}` (`management.py:620`, admin + CSRF). Tabela `usuarios`. Regra de quem pode alterar quem: `_exigir_conta_gerenciavel` (`management.py:556`).
- Destino proposto: OPER.
- Observação: exclusão de conta e de nível é destrutiva, e tem confirmação (`UsersPage.tsx:117, 129, 167`). Contas e níveis são dado pessoal.

### IagoDev > Turnos — `/inicio/turnos`
- Componente: `web/src/pages/home/ShiftsPage.tsx:73`. Rota `RequireAdmin` (`App.tsx:186`).
- Endpoints: `GET /api/v1/management/shift-parameters` (`management.py:245`, admin); `POST` (`management.py:254`, admin + CSRF); `DELETE /{id}` (`management.py:282`, admin + CSRF). Tabela de turnos não confirmada. Calendário produtivo (`management.py:304-359`) é outra área, não usada nesta tela.
- Destino proposto: OPER.
- Observação: turno pode afetar cálculos de capacidade e OEE (não verificado). Remover pede confirmação (`ShiftsPage.tsx:219`).

### IagoDev > Apontamento por setor — `/inicio/apontamento-por-setor`
- Componente: `web/src/pages/home/ActingSectorPage.tsx:21`. Rota `RequireAdmin` (`App.tsx:187`).
- Endpoints: `GET /api/v1/management/operator-sectors` (`management.py:828`, admin). O modo "como setor" é controlado no frontend: `setActingSector` manda o cabeçalho `X-Acting-Sector` em toda chamada (`web/src/api/client.ts:66`).
- Destino proposto: OPER.
- Observação: RISCO. Com o modo ativo, toda chamada leva o cabeçalho. O backend aceita só para gestão e troca o setor da sessão (`backend/api/dependencies/auth.py:46-81`). Não verifiquei se os apontamentos gravados ficam com a identidade do setor. Confirmar antes de construir.

### IagoDev > Sistema — `/inicio/sistema`
- Componente: `web/src/pages/home/SystemPage.tsx:20`. Rota `RequireAdmin` (`App.tsx:191`).
- Endpoints: `POST /api/v1/system/rebuild-frontend` (`backend/api/routers/system.py:121`, `require_admin_user` + CSRF). Roda `npm run build` no servidor e devolve o log.
- Destino proposto: OPER.
- Observação: ação de servidor (executa build). Tem confirmação. Depende de Node no servidor.

### Áreas (Dobra e Corte, Usinagem, Serra, Solda, Pintura, Protótipo, Projetos/Ferramentaria) — `/areas/:areaId`
- Componente: `web/src/pages/areas/AreaPage.tsx:28` e `web/src/pages/areas/AreaQueuePanel.tsx:40`. Rota dinâmica `App.tsx:200`.
- Endpoints: `GET /api/v1/operations/resources?...` (`AreaPage.tsx:34`, auth não confirmada nesta leitura). Fila manual: `GET /api/v1/areas/{area}/queue/resources` (`backend/api/routers/area_queue.py:61`), `GET /queue` (`area_queue.py:75`), `POST` (`area_queue.py:87`), `PUT` reordena (`area_queue.py:101`), `DELETE /{entry_id}` (`area_queue.py:117`). Todas com `require_management_user` + `_autorizar_area` (`area_queue.py:25`). Tabela da fila não confirmada.
- Destino proposto: OPER.
- Observação: a rota aceita qualquer `areaId` na URL; o bloqueio está no backend (`_autorizar_area`). A reordenação muda a ordem de execução das operações.

## Rotas de App.tsx que não estão no menu (navigation.ts)

Órfãs de redirect, sem entrada no menu:
- `/inicio/setores` → `/inicio/visao-geral` (`App.tsx:178`)
- `/inicio/alertas` → `/auditoria/alertas-inconsistencias` (`App.tsx:179`)
- `/consulta-operacional/tempo-mes` → `/analises/horas-utilizacao` (`App.tsx:198`)
- `/auditoria/apontamentos` → `/auditoria/eventos-producao` (`App.tsx:226`)
- `/auditoria/inconsistencias` → `/auditoria/alertas-inconsistencias` (`App.tsx:228`)
- `/relatorios/gerencial`, `/relatorios/producao`, `/relatorios/perdas`, `/relatorios/indicadores`, `/relatorios/dados-analiticos` (`App.tsx:232-236`)
- `/rastreabilidade/linha-do-tempo` → `/rastreabilidade/op-produto` (`App.tsx:239`)

Menu aponta para redirect (não é órfã, mas a aba leva a outra rota):
- `/inicio/andon` → `/andon`, `/inicio/mapa-fabrica` → `/mapa-fabrica` (`App.tsx:180-181`; abas em `navigation.ts:179-180`)

Fora do menu de gestão, por desenho: `/login`, `/andon`, `/mapa-fabrica`, `/operador/*`, `/ajuda`, `/ajuda/:manual`, `/ajuda/:manual/:topico`, `/manutencao`, `*` (`App.tsx:165-247`).

## Riscos principais
1. Envios ao Protheus: Reenviar dispara novo envio real sem confirmação. Descartar não tem desfazer.
2. Permissão: o backend confere nas rotas admin que li. Não achei tela que dependa só do frontend. Dois descasamentos: Andon (gestão sem `andon_access` passa na tela e leva 403) e o modo "como setor". Não verificado: auth de `/operations/resources`.
3. Ação destrutiva na consulta: Desfazer em Alterações (só desenvolvedor, com confirmação); Remover contato em Chamadas do IagoDev (permanente, com confirmação); exclusão de conta e de nível em Cadastro (com confirmação).
4. Dados pessoais: Chamadas da Gestão mostra e-mail e crachá para qualquer gestão; Alterações e Log mostram nome de usuário; Chamadas do IagoDev mostra ID do Telegram; a IA envia perguntas a provedor externo.
5. Rotas órfãs: 9 redirects sem menu (lista acima). Andon e Mapa apontam para redirect.
6. Falha silenciosa: no Log do Sistema, erro do resumo esconde os botões de área sem aviso.
7. Apontamento por setor: o modo "como setor" manda `X-Acting-Sector` em todas as chamadas, e o backend aceita para gestão. Não verifiquei se os apontamentos saem com identidade do setor.
8. Sistema: "Reiniciar build" roda `npm run build` no servidor via API (admin, com confirmação).


# Anexo — inv_D_regras_calculo

# Investigação D: regras de cálculo vigentes (somente leitura, 10/11/2026)

Repo: `Gestor de Peças - Area de Testes`. Caminhos relativos à raiz do repo.

## 1. Setup como tempo produtivo — Confirmado (com uma divergência de base)
- Regra: AGENTS.md:123 ("Setup é produtivo e não reduz Disponibilidade nem Performance").
- Onde é decidido: `mes/analytics/oee.py:58-68`. SETUP está em `_WORKED_CATEGORIES` (entra no numerador e no denominador da Disponibilidade) e em `_SUPPORTING_CATEGORIES` (crédito de apoio somado a S_boas no numerador da Performance, `oee.py:177-183`). Efeito: setup não derruba nem A nem P; é neutro em P (soma igual em cima e embaixo).
- Classificação produtiva geral: `mes/domain/manufacturing_rules.py:235-247` (`is_productive` = produção, setup, atividade sem OP).
- **Divergência**: RETRABALHO está em `_WORKED_CATEGORIES` do OEE (`oee.py:61`), mas `is_productive` o EXCLUI (`manufacturing_rules.py:238-246`). Bases que usam `is_productive` (ex.: `productive_seconds` em `mes/services/management.py:410-414`, tempo operacional do MTBF em `mes/services/industrial_analytics.py:509-513`) diferem das bases do OEE (`worked_seconds`). O Diretoria usa `_WORKED_CATEGORIES` (`mes/services/director_summary.py:19,408`). "Horas trabalhadas" pode ter dois números.

## 2. OEE / Disponibilidade / Performance / Qualidade / FTT — Confirmado + divergências
Fonte canônica: `mes/analytics/oee.py:130` `calculate_oee` (contrato `OEE_CONTRACT` em `oee.py:25-32`, versão `corporativa-2026-09-24` em `oee.py:21`). Entrada temporal: `oee_seconds_by_category` (`oee.py:105-127`) tira parada planejada da categoria DOWNTIME.
- Disponibilidade = T_trabalhado / T_disponível (`oee.py:208`). T_trabalhado = produção+setup+retrabalho+atividade sem OP (`oee.py:168`). T_disponível = T_trabalhado + parada (não planejada) + DESCONHECIDO (`oee.py:169-173`). Fila e sem demanda ficam fora (`oee.py:174-175`). Fora de turno fica fora.
- Performance = (S_boas + T_apoio) / T_trabalhado (`oee.py:183`, `oee.py:311`). S_boas = tempo padrão OFICIAL (Protheus+manual) × boas do período (`management.py:173-194`, `_good_quantity_in_period` `management.py:2050`). Sem padrão para todas as boas = NOT_CONFIGURED; parcial = PARTIAL (`oee.py:302-329`). >100% não é cortado, gera alerta (`oee.py:313-321`). Performance "estimada" é cálculo paralelo separado (`management.py:437-450`).
- Qualidade: NÃO existe métrica "Qualidade" separada no OEE; o 3º fator é o FTT. OEE = A × P × FTT (`oee.py:351`).
- FTT = boas / (boas + refugo + retrabalho), descontando recuperados de retrabalho (`oee.py:36-56`, `oee.py:219-225`).
- Exceção sem demanda: 100/0/0, FTT não aplicável (`oee.py:244-288`).
- Consumidores: só `ManagementService.get_overview` chama `calculate_oee` (`management.py:421`, `437`, `514`, `531`, `629`: geral, recurso, setor). Diretoria lê `overview.kpis.oee` (`director_summary.py:1-8`, `315`, `165`).
- Cálculos paralelos identificados:
  - `management.py:460-474` Utilização = worked/operational = **mesmo número da Disponibilidade** com outro nome (operational_seconds == available_seconds, `oee.py:186-187`); Produtividade = produção bruta/operacional; AE = net/available.
  - Diretoria: horas de parada por setor recalculadas como `tempo_parada_segundos - parada_planejada_segundos` (`director_summary.py:138-148`) e trechos físicos reconsolidados (`director_summary.py:348-356`) a partir de `IndustrialAnalyticsService.physical_inputs` — mesma função de consolidação, mas segunda passagem.
  - Frontend (web/src): nenhuma recomposição de A/P/FTT/OEE encontrada (grep de fórmulas em `pages/analytics`, `pages/director`, `ManagementOverviewPage`, `utils/dashboardCards`). Há agregações locais em outras telas:
    - Padrão×Real: desvio % global somado no navegador `Σreal−Σpadrão / Σpadrão` (`web/src/pages/analytics/AnalyticsPages.tsx:684-720`); não existe esse total no backend.
    - Cronoanálise: média geral ponderada por amostras misturando produtos/operações diferentes, e `average: 0` quando não há amostra (`AnalyticsPages.tsx:759-762`) — zero sem semântica.
    - Variação vs período anterior calculada na tela (`web/src/pages/ManagementOverviewPage.tsx:54`); média por recurso `total_seconds / resource_count` (`ManagementOverviewPage.tsx:438`).
  - Relatórios operacionais: médias próprias por OP com fallback `0` quando sem dado (`mes/services/operational_reports.py:133`, `321`, `438`); usam timeline + divisão igualitária (`operational_reports.py:191-230`), não o tempo físico consolidado.
  - Auditoria atual (`mes/services/audit.py`) não calcula KPI: só lista inconsistências; `reliability_percentage` fixo `None` (`audit.py:428`, `457`).
  - Planilha executiva (`backend/api/report_workbook/executive.py:216-226`) só apresenta colunas do overview; não recalcula.
  - SQL: nenhum cálculo de OEE/FTT em `.sql`; o banco só recorta o tempo dos estados (ver seção 4).

## 3. Tempo de máquina × tempo de OP × pessoa-tempo — Confirmado + riscos
- Tempo de máquina (relógio do recurso): `mes/analytics/physical_time.py:67` `consolidate_physical_time` — união temporal por recurso (identidade canônica, `physical_time.py:96-103`). Duas OPs no mesmo estado contam uma vez; produção+parada simultâneas = produção prevalece (`physical_time.py:281-288`); estados diferentes em conflito viram DESCONHECIDO (`physical_time.py:295`), que entra no denominador da Disponibilidade.
- Fonte do tempo físico: estados de recurso (`eventos_estado_recurso`) quando existem; senão timelines dos apontamentos + nestings (`management.py:1118-1127`).
- Tempo de OP: timeline por apontamento (`mes/analytics/timeline.py:61`); produção simultânea é dividida igualitariamente (`mes/analytics/rateio.py:13`, `70`, `125`) em `standard_vs_actual` (`industrial_analytics.py:332-351`) e `operational_reports.py:196`. Setup/parada/retrabalho continuam atribuídos inteiros a cada OP (`rateio.py:129-133`) — soma por OP de setup/parada PODE passar do tempo da máquina.
- Pessoa-tempo: Diretoria divide trechos por pessoas (`director_summary.py:426-480`, `_split_by_people` `577`).
- **Risco de dupla contagem**: `cutting_without_interval_seconds` (nesting legado sem início/fim) é somado em PRODUÇÃO sem checar sobreposição e mesmo quando a fonte é o estado de recurso (`management.py:330-341`, `354-355`, `403-404`).
- **Risco**: com estados disponíveis, TODA a base vira estado (`management.py:1118`); apontamento de recurso sem estado sai do tempo físico.

## 4. Eventos que atravessam o período / abertos — Confirmado, mas com três relógios
- Estados: banco recorta início em `max(início, filtro.início)` e fim em `min(fim_estado ou agora, filtro.fim, agora)` (`app/database/database.py:4978`, filtro `~4998-4999`, recorte `~5022-5041`, relógio `agora_db()`).
- Prefetch em memória replica o recorte (`management.py:1931-1950`), mas congela `agora=datetime.now()` (`management.py:886`) e não `self._now()` — **diverge do relógio injetado** (simulação/testes/Diretoria com `now`).
- Apontamentos: fim aberto = `min(self._now(), filtro.fim)`, depois clip (`management.py:1136-1147`; `industrial_analytics.py:943-952`; nesting `industrial_analytics.py:167-176`).
- Diretoria: período termina 23:59:59 de hoje (`director_summary.py:48-69`), confia no corte em "agora" do banco.

## 5. zero / sem registros / não aplicável / não configurado / dados insuficientes — Confirmado
- Enum `DataAvailability` (`mes/domain/industrial.py:84-90`): disponivel, parcial, sem_registros, dados_insuficientes, nao_configurado, nao_aplicavel.
- Contrato `MetricValue(value, availability, unit, reason)` (`mes/contracts/management.py:41-50`).
- Uso no OEE: `oee.py:333-365` (sem dado → value None + sem_registros; OEE com 1-2 componentes faltando → dados_insuficientes; 3 faltando → sem_registros); NOT_CONFIGURED para Performance sem padrão (`oee.py:304-310`); NOT_APPLICABLE para FTT sem demanda (`oee.py:275-280`).
- MTBF/MTTR usam o mesmo enum como string solta no payload, não MetricValue (`industrial_analytics.py:530`, `586-603`).
- Diretoria: cards `produzido` (`director_summary.py:162`) vem com fallback `0` se ausente (`.get("good", 0)`) — **zero sem semântica**.

## 6. MTBF/MTTR, Capacidade/Utilização, Padrão×Real, Cronoanálise — parcial
- MTBF/MTTR: `industrial_analytics.py:477-605`. MTBF = tempo operacional (is_productive, sem retrabalho) / nº falhas; MTTR = tempo de reparos CONCLUÍDOS / nº concluídos. Falha = motivo de manutenção corretiva no catálogo e não programada (`manufacturing_rules.py:506`, `industrial_analytics.py:542-548`).
  - **Divergência interna**: MTTR por recurso = segundos de TODAS as falhas (inclusive em andamento) / nº de falhas (`industrial_analytics.py:574-579`), diferente do MTTR geral (`565`).
- Padrão×Real: `industrial_analytics.py:267-330`. Real = produção da timeline (ou rateio/divisão igualitária) recortada ao período; quantidade boa = TOTAL do apontamento (`industrial_analytics.py:287`) — **apontamento que atravessa o período distorce tempo real por peça**.
- Cronoanálise: `industrial_analytics.py:399-425` = média/mediana/min/max/desvio de `tempo_real_por_peca` do Padrão×Real (herda a distorção acima). Amostras para o tempo padrão estimado são mais estritas (`industrial_analytics.py:352-397`: só finalizadas, inteiras na janela, sem rateio).
- Capacidade/Utilização: `industrial_analytics.py:627-760`. Capacidade = tempo PLANEJADO do calendário produtivo no período inteiro (não até agora), fallback expediente global (`industrial_analytics.py:715-725`). Carga = produção+setup+retrabalho do tempo físico consolidado (`industrial_analytics.py:733-736`). Utilização = carga/capacidade (`~745`). Capacidade em peças não é publicada (`627-640`).
  - **Divergência de nome e base**: existem DUAS "Utilização": (a) `kpis_estendidos.utilization` = worked/available = igual à Disponibilidade OEE (`management.py:460-480`); (b) capacidade = carga/calendário. E a carga (b) EXCLUI atividade sem OP, que o OEE conta como trabalhada. Três bases de "tempo trabalhado": OEE (prod+setup+retrab+sem OP), `is_productive` (prod+setup+sem OP), capacidade (prod+setup+retrab).

## 7. Boas, refugo, retrabalho somados como "boa" — Confirmado separados, com ressalva
- Produção = só boas (AGENTS.md:121; `docs/REGRAS_MANUFATURA_CANONICAS.md:19-21`). Overview soma boa/refugo/retrabalho em grandezas separadas (`management.py:142-145`, `205-245`).
- `quantidade_atendida = boas + refugo` e conclusão da OP por boas+refugo (`manufacturing_rules.py:182-226`), exposto em `planned_vs_actual` (`industrial_analytics.py:446`).
- **Divergência de documentação**: AGENTS.md:122 diz "Refugo não completa a quantidade planejada da OP", mas `docs/REGRAS_MANUFATURA_CANONICAS.md:25-38` e o código dizem que boas+refugo atinge a meta (AGENTS.md:252 também: "Refugo continua consumindo o planejado"). Código segue a regra nova; AGENTS.md:122 está desatualizado.
- Performance usa boas físicas incluindo recuperadas (`oee.py:158-162`).

## 8. Instante de referência / as_of — Não encontrado nos endpoints analíticos
- O overview (`get_overview`, chaves em `management.py:780-855`) NÃO devolve instante de referência: só `periodo`, `kpis`, `kpi_contract`, `kpi_time_bases` etc. O "agora" usado no recorte fica interno.
- Só as explicações dos números (gaveta "por que este valor") trazem `calculated_at`: `mes/services/metric_explanation.py:187`, `316-337`; `kpi_explanation.py:292`; `director_explanation.py:406`, `426`; `cut_explanation.py:149`.
- `data_quality.status` do overview é sempre `parcial`, fixo (`management.py:~851`).
- Outros campos soltos: Encontrados: `calculated_at` em `physical_consolidation` (`management.py:1132`), `reference_time` só no bloco de simulação (`management.py:595`), `generated_at` em `management_insights.py:106` e `andon.py:385`, `calculado_em` em `standard_time.py:262`. Diretoria devolve só `periodo.inicio/fim` (`director_summary.py:160`).

---

# Etapa 2 — Auditoria analítica (tipos 01 e 02) — 10/11/2026

Entregue: tela `/auditoria/analitica` (menu Auditoria → "Auditoria analítica"), rotas `GET /api/v1/audit/reports`, `/audit/reports/{01|02}` e `/audit/reports/{01|02}/export.csv` (todas com `require_management_user`), serviço `mes/services/audit_reports.py`. As telas antigas (Eventos de Status / Eventos de Produção) continuam no ar; a remoção é a Etapa 5.

Regra de período e de evento aberto (também devolvida no campo `regra_periodo`): entra todo evento que toca o período; o tempo contado vai do maior entre início do evento e início do período até o menor entre fim do evento, fim do período e o `as_of`. Evento aberto aparece sem fim e conta até o `as_of`.

Estados: `com_dados`, `zero` (há linhas, medida principal soma zero), `sem_registros`, `indisponivel` (fonte não existe; não é zero) e `erro` (HTTP 500 com `estado: "erro"` e `as_of`).

Validação: pytest (`test_audit_reports.py` + testes de auditoria do `test_web_api.py`), vitest (tela nova, telas antigas e gerencial), build, e conferência no navegador no banco TEST: tipo 01 = tela antiga (327 eventos/38 recursos em out–nov; 202 no período padrão, mesmos 19 campos); tipo 02 = tela antiga (0 nos dois — o TEST não tem eventos de produção no período, então a comparação com dados de produção ficou só nos testes automáticos). Revisão Codex: 2 achados, ambos corrigidos (as_of lido depois da consulta; detalhe fecha ao trocar de página).

## Decisões tomadas sem o usuário

1. Recurso e OP comuns usam a barra global (busca exata). Na tela antiga do tipo 01 eram busca por trecho e seletor por nome. Reversível: basta voltar o seletor por trecho só no tipo 01.
2. Os dois tipos paginam de 100 em 100. Isso acaba com o corte de 200 linhas da tela antiga de produção.
3. Os filtros próprios do tipo 01 (Status, Classificação, Situação) ficam guardados ao trocar para o 02, com aviso de "ignorado", em vez de serem apagados.
4. A exportação é um CSV feito no backend: ";" + BOM, todas as linhas e todos os campos, com o cabeçalho `X-Gestor-As-Of`. Fica protegido contra fórmula no Excel.
5. `as_of` = relógio da API sem microssegundos, lido depois da consulta e limitado ao fim do período.
6. O item "Auditoria analítica" vai no topo da seção Auditoria. A página padrão da seção não mudou.
7. `management.test.tsx` agora espera 50 rotas gerenciais. Antes estava em 48, mas já falhava com 49 por causa de um commit anterior de outra pessoa.
8. Para conferir no navegador, criei a conta de teste `claude_auditoria_teste` (admin) só no banco TEST. A senha está fora do Git.
9. ATENÇÃO: o commit 548e769 foi enviado para o GitHub (origin/master) sem que eu rodasse push. Quem enviou foi um gancho automático do repositório ("[auto-push]"), que dispara depois de cada commit. Não desfiz o envio, porque isso pediria um push forçado. O commit só tem arquivos desta etapa.

---

# Etapa 3 — Auditoria analítica, tipos 03 a 21 — 11/11/2026

Entregue: os tipos 03–21 em `/auditoria/analitica`, agrupados em Produção e rastreio, Paradas e tempos, Qualidade, Indicadores e Dados e sistema. Cada tipo chama o serviço que a tela de origem já usa (`mes/services/audit_reports.py`, funções `_t03`…`_t21`). O catálogo (`GET /audit/reports`) só lista os tipos que a conta pode abrir; tipo fora da permissão dá 403. Conta sem nenhum tipo recebe 403 no catálogo.

Contas que saíram do navegador e foram para o servidor: Desvio % do Tempo padrão (tipo 08, só com padrão > 0), média ponderada da Cronoanálise (tipo 09, null sem amostra), somas da Capacidade (tipo 10, vêm do resumo do próprio serviço). O OEE (tipo 11) é o mesmo `resource_kpis`/`kpis` da tela Início (fonte única `mes/analytics/oee.py`). Valor sem dado sai como `null` e a tela mostra "sem registros"; medida sem valor nenhum não vira estado "zero".

Permissões: gestão (padrão), qualidade (21 Decisão de RNC), admin (17 Alterações, 18 Log do sistema, 19 Envios ao Protheus). 13 Linha do tempo da OP exige OP e respeita o escopo de setor (403 fora dele). 19 e 21 são só consulta: as ações continuam nas telas próprias. 20 Chamadas mostra e-mail e crachá e um aviso por chamada (sem confirmação, enviando, na tela, falhou) no `as_of`.

Validação: `test_audit_reports.py` (13), `test_chamadas.py`, teste de auditoria do `test_web_api.py` percorrendo os 21 tipos (gestor vê, admin-only dá 403), vitest da tela (5), `tsc`. Sondagem no TEST (400 dias): todos os tipos respondem; 03–09, 12–16, 19 e 21 dão "sem registros" (o TEST não tem produção), 10 e 11 dão "zero", 17/18/20 têm linhas.

Revisão Codex (high): 2 achados. Corrigido: medida ausente virava estado "zero". Descartado: "tipo 20 não aplica escopo de setor" — a tela de origem (`/chamadas/admin/historico`, `require_management_user`) também não aplica; a regra é usar a permissão do módulo de origem. Se quiser restringir chamadas por setor, é mudança nas duas telas.

## Decisões tomadas sem o usuário (Etapa 3)

1. Nenhum tipo da Auditoria mostra R$: custo continua só na Diretoria.
2. "Utilização" estendida (`kpis_estendidos.utilization`) não aparece separada no tipo 11, porque é igual à Disponibilidade (decisão do usuário: ela passa a se chamar Disponibilidade).
3. Fontes sem filtro de período (Alterações, Envios, Chamadas, RNC) leem os 200 mais recentes (Alterações 500, Log 1000) e filtram o período no servidor, com aviso na tela.
4. `telegram_status` saiu do router de chamadas para `app/database/chamada_repository.py`, para a Auditoria usar a mesma regra sem importar router.
5. Tipo 16 (Confiabilidade) fica vazio quando nenhum registro foi analisado, em vez de mostrar 100%.
6. O estado do tipo 04 é calculado pela lista de paradas; o total do resumo pode vir de fora da lista e há aviso quando diferem.
7. Um único commit para a Etapa 3 em vez de um por grupo: os grupos dividem o mesmo arquivo de serviço, a mesma rota e a mesma tela; separar exigiria commits parciais de arquivo sem ganho.

---

# Etapa 4 — Dashboard da Diretoria — 11/11/2026

Entregue: no Painel da Diretoria, uma linha nova com até 6 indicadores acima dos 4 cartões em R$: Peças boas e Refugo (tipo 02), Horas paradas não planejadas (tipo 04), OEE e Disponibilidade (tipo 11), Desvio do tempo padrão (tipo 08). Cada número é o `summary` do tipo da Auditoria (`audit_reports.indicadores_diretoria`), rodado uma vez por tipo no mesmo `as_of`; nada é recalculado. Rota nova `GET /diretoria/indicadores?periodo=` (mesma guarda da Diretoria). Clicar num indicador grava o período no filtro gerencial (setor/recurso/OP limpos) e abre `/auditoria/analitica?tipo=XX`.

Mesmo relógio: as rotas da Auditoria passaram a usar `request_now_func` (o relógio da Diretoria e da simulação).

Corrigido: `director_summary.py` (cartões do Painel e Ficha) usava `.get("good", 0)`; sem dado de produção agora é `null` e a tela mostra "sem registros" (o texto da Ficha diz "sem registros de produção").

Validação: `tests/test_director_api.py` (inclui o teste que compara cada indicador com `/audit/reports/XX` no mesmo período e `as_of`, "sem registros" = null, tipo quebrado não derruba os outros, 403 para todo nível fora da Diretoria), `test_director_summary.py` (produzido null), demais testes da Diretoria e da Auditoria (97 ok), vitest `director-page` (25) e `auditoria-analitica` (5), `tsc`.

Revisão Codex (high): 2 achados. Corrigido: erro de um tipo derrubava a rota inteira (500); agora o indicador sai com estado "erro" e "não foi possível ler". Descartado/pendente: "ao abrir a Auditoria num período em andamento o as_of avança" — é verdade, mas a Auditoria mostra o próprio `as_of` na tela; congelar exigiria um parâmetro `as_of` novo no contrato da Auditoria. Fica como pendência.

## Decisões tomadas sem o usuário (Etapa 4)

1. Os 4 cartões em R$ continuam (as explicações "de onde vem o número" dependem deles); os 6 indicadores entram numa linha nova acima. Total na tela: os 6 da Auditoria + os 4 de R$ que já existiam.
2. Horas paradas do indicador = só as não planejadas (`unplanned_downtime_seconds` do tipo 04), igual ao cartão "Horas paradas" que a Diretoria já usava.
3. Indicador cujo tipo a conta não abre não aparece (a Diretoria abre todos os quatro tipos usados).
4. Período: os mesmos nomes da Diretoria (hoje/semana/mês); ao abrir a Auditoria, só as datas do período vão para o filtro e os demais filtros são limpos, para o número bater.

# Etapa 5 — Menu e redirecionamentos — 11/11/2026

Entregue: 12 telas só de consulta saíram do menu. A rota antiga continua existindo e leva para a Auditoria analítica no tipo certo, mantendo a query string (`RedirectToAudit` em `web/src/App.tsx`). Os filtros (período, setor, recurso) vêm do filtro gerencial compartilhado, então os atalhos da Visão Geral continuam abrindo com o mesmo filtro.

Mapa rota antiga → tipo: `/analises/oee` → 11 · `/analises/paradas` → 04 · `/analises/qualidade` → 06 · `/analises/tempo-padrao-real` → 08 · `/analises/cronoanalise` → 09 · `/analises/capacidade-gargalos` → 10 · `/analises/confiabilidade` → 12 · `/auditoria/eventos-status` → 01 · `/auditoria/eventos-producao` e `/auditoria/apontamentos` → 02 · `/auditoria/alertas-inconsistencias`, `/auditoria/inconsistencias` e `/inicio/alertas` → 15 · `/auditoria/confiabilidade` → 16 · `/inicio/log-sistema` → 18.

Ficam no menu (pedido): Consulta de OP, Envios ao Protheus (Reenviar/Descartar), Decisão de RNC, Cadastro, Alterações, Sistema. Página padrão de Análises: Horas & Utilização; da Auditoria: Auditoria analítica.

Validação: vitest `management.test.tsx` (67 ok; menu com 38 rotas; confere que as 4 rotas-exemplo saíram e as 6 pedidas ficaram; o clique em "Ver análise relacionada" da Visão Geral cai na Auditoria analítica), `tsc` limpo.

Revisão Codex (high): sem achados.

## Decisões tomadas sem o usuário (Etapa 5)

1. Regra usada: sai do menu só a tela que apenas consulta e cujo destino no inventário é exatamente um tipo da Auditoria.
2. Ficam, apesar de terem tipo parecido: Horas & Utilização (mistura as 3 bases de tempo, sem tipo único); Rastreabilidade (o link "Rastrear OP" usa `?op=`, que a Auditoria não lê); Chamadas da Gestão (destino do sininho); SPC (gráfico de controle, exclusiva da Qualidade; o tipo 07 é de gestão); Produção realizada e Planejado × Realizado (destino indefinido DASH/OPER); Relatórios (exporta .xlsx); telas de operação (Execução das OPs, OPs em andamento, Visão Geral, Recursos, Pausas, Crachás, Turnos, Apontamento por setor, Chamadas do IagoDev).
3. Os arquivos das páginas antigas não foram apagados (volta atrás = devolver a rota e a aba). Os gráficos das antigas Análises deixam de aparecer; a Auditoria mostra o resumo e a tabela do tipo.
4. Textos não alterados (para não mexer no visual): botões da Visão Geral ainda dizem "Abrir Análises: OEE" etc., e a ajuda `src/help/content/gestao/70-analises-oee.md` ainda cita `/analises/oee`. Ambos funcionam pelo redirecionamento; ficam como pendência de texto.

# Etapa 6 — Validação final e relatório — 11/11/2026

Validação:
- vitest, um arquivo por vez: `auditoria-analitica` (5), `director-page` (25), `auditoria-eventos` (4), `management` (67) — todos ok.
- `tsc` limpo; `npm run build` ok (só o aviso de pacote acima de 500 kB, que já existia). O projeto web não tem ESLint configurado; o `tsc` faz esse papel.
- pytest `test_director_summary.py` + `test_director_api.py`: 47 ok.
- Navegador (API única na 8001, banco `gestor_pecas_test`, development, IA e Telegram desligados, conta de teste admin): `/analises/oee` abre `/auditoria/analitica?tipo=11`; o grupo Análises do menu só tem Horas & Utilização; Log do Sistema saiu; Diretoria mostra os 6 indicadores com o `as_of` e "Abrir na Auditoria".

Achado na conferência e corrigido: com o dado real de um dia sem produção, o cartão "Produzido" da Diretoria mostrava "0 peças" enquanto o tipo 02 dizia "sem registros". A Visão Geral manda `good: 0` junto com `availability: sem_registros`, e o resumo da Diretoria só olhava o número. Agora `_produced` em `mes/services/director_summary.py` devolve `null` quando a fonte diz "sem registros" (painel e ficha); teste novo `test_a3`. Prova no navegador: "Produzido — sem registros". Codex (high): sem achados.

Observação: a API da 8001 estava rodando código de antes da Etapa 4 (sem `--reload`); foi reiniciada com o código atual.

## Commits das etapas 2 a 6

- 548e769 — Auditoria analítica, tipos 01 e 02, `as_of`, estados e CSV (Etapa 2)
- 4704cdb — tipos 03 a 21 (Etapa 3)
- bb3f5a5 — 6 indicadores da Diretoria lidos da Auditoria (Etapa 4)
- 25ac11d — telas de consulta saem do menu e redirecionam (Etapa 5)
- commit deste relatório — "Produzido" sem registros + relatório (Etapa 6)

## Pendências

1. `as_of` móvel: ao abrir a Auditoria a partir da Diretoria num período em andamento, o `as_of` avança (achado 2 do Codex na Etapa 4). Congelar pede um parâmetro `as_of` novo no contrato da Auditoria.
2. No indicador Disponibilidade, o estado interno vem "zero" mesmo com valor 100% (o estado é o do relatório tipo 11 inteiro). A tela mostra 100% certo; só o rótulo interno é impreciso.
3. Textos: botões da Visão Geral ("Abrir Análises: OEE" etc.) e a ajuda `70-analises-oee.md` ainda citam as telas antigas; funcionam pelo redirecionamento.
4. Gráficos das antigas Análises não aparecem mais no menu (arquivos mantidos); se fizerem falta, viram parte da Auditoria ou voltam ao menu.
5. Rastreabilidade não saiu porque a Auditoria não lê `?op=`; dá para tirar depois que a Auditoria aceitar filtro de OP pela URL.

## Decisões tomadas sem o usuário (Etapa 6)

1. Corrigir na hora o "Produzido 0 × sem registros" (correção pequena e reversível, na mesma linha da decisão da Etapa 4) em vez de deixar como pendência.
2. Reiniciar a API da 8001 para validar o código atual (era a única API; mesma porta e mesmo banco de teste).

## Revisão da aba Diretoria (11/11/2026)

Pedido: a Diretoria já tem aba própria; decidir se o que existe fica, é completado pelo plano ou sai. Decisão: a própria `/diretoria` é a casa do Dashboard definitivo (já protegida por `require_diretoria_user`); não foi criada segunda tela. O topo do Painel são os 6 indicadores do plano (Etapa 4), cada um abrindo a Auditoria filtrada. Contrato da API não mudou (o backend segue mandando os campos; o front só deixou de mostrar).

| Item da aba | Onde | Plano cobre? | Destino | Motivo |
|---|---|---|---|---|
| 6 indicadores (Peças boas, Refugo, Horas paradas não planejadas, OEE, Disponibilidade, Desvio do tempo padrão) | Painel | Sim | Mantido | São o Dashboard do plano; clique leva à Auditoria tipo 02/04/11/08 |
| Cartão "Produzido" | Painel | Sim (Peças boas) | Removido | Mesmo número de Peças boas com outro nome |
| Cartão "Horas paradas" | Painel | Sim (Horas paradas não planejadas) | Removido | Mesma conta (só paradas fora do planejado) com nome mais curto |
| Cartão "Eficiência" | Painel | Sim (OEE) | Removido | É o OEE com outro nome |
| Cartão "Custo das paradas" (R$) | Painel | Não | Mantido | Só existe aqui; custo em R$ é exclusivo da Diretoria |
| Aviso "faltam custos de N recursos/pessoas" | Painel | Não | Mantido | Explica custo parcial |
| Aviso "eficiência acima de 100%" | Painel | Não | Mantido | Avisa OEE impossível (tempo padrão errado); vale para o indicador OEE acima |
| "Onde mais perdemos" (top 3 setores, horas, R$, motivo, abre a Ficha) | Painel | Não | Mantido | Só existe aqui; traz R$ e o motivo, e é a porta para a Ficha |
| "Setor que melhor aproveitou / mais desperdiçou o tempo" | Painel | Não | Mantido, sem o zero | Ranking por setor não existe no plano; mas quando o melhor setor tem 0% (caso do TEST: "Corte, eficiência 0%") os dois cartões viram "Sem dados", porque 0% como "melhor" não diz nada |
| Ficha do setor: Trabalhou, Produzido, Parado, Custo do trabalho, Custo das paradas, Paradas por motivo, Quem operou, Tempo que não entra no custo | Ficha | Parcial (só no total da fábrica) | Mantido | É a visão por setor/recurso com R$; a Auditoria não tem essa visão consolidada por setor com custo |
| Edição do valor da hora (recurso e pessoa) | Custos | Não | Mantido | Configuração que alimenta todo R$; só existe aqui |

Arquivos: `web/src/pages/director/DirectorPanel.tsx`, `web/src/test/director-page.test.tsx`, `web/src/test/director-explanation.test.tsx` (este último também passou a montar a página com roteador e filtros; quebrava desde a Etapa 4 porque os indicadores navegam para a Auditoria).

Validação: vitest director-page 26 e director-explanation 7 passaram; tsc limpo; build ok; conferido no navegador em `/diretoria` (6 indicadores, Custo das paradas, Onde mais perdemos e destaques "sem dados" no lugar de "Corte 0%").

## Decisões tomadas sem o usuário (revisão da aba Diretoria)

1. Manter `/diretoria` como o Dashboard definitivo em vez de criar outra tela (pedido explícito: não criar segunda tela).
2. Esconder no front, sem mudar a API: os campos `produzido`, `horas_paradas` e `eficiencia_oee` continuam no `/diretoria/painel` (reversível; `eficiencia_oee` ainda alimenta o aviso de acima de 100%).
3. Manter os destaques de melhor/pior setor em vez de removê-los, só trocando o "0%" por "sem dados" (o ranking por setor não existe em outro lugar).
4. Manter a Ficha inteira, inclusive Produzido e Parado por setor: repetem a Auditoria só no total da fábrica, não por setor com custo.

## Ajustes de 11/11/2026: Excel em vez de CSV e cards acima dos filtros

Pedido do usuário, válido para a Auditoria analítica, a Diretoria e toda tela nova: exportar só planilha Excel (.xlsx), nunca CSV; cards principais no topo, filtros embaixo deles, tabela por último.

- Auditoria analítica: a rota `export.csv` saiu (agora 404) e entrou `GET /api/v1/audit/reports/{tipo}/export.xlsx`, com o mesmo gerador openpyxl dos Relatórios. A planilha traz título (A1), filtro usado (A2), `Referência (as_of)` (A3), cabeçalho com todos os campos na linha 5 e todas as linhas a partir da 6. Texto passa pelo `safe_text` (proteção contra fórmula).
- Auditoria analítica: cards e a linha da Referência subiram para logo abaixo do título (prop `summary` do `PageFrame`), em todos os tipos.
- Diretoria: sem mudança. Ela não tem exportação, e o seletor Hoje/Semana/Mês fica na barra de navegação (junto de Painel/Ficha/Custos), com os indicadores logo abaixo; não há barra de filtros acima dos cards para inverter.

## Ajustes globais de 11/11/2026

**Excel no sistema inteiro.** O único CSV restante (Relatórios, `export.csv`) saiu; fica a planilha .xlsx técnica e simples. Os roteiros antigos de homologação `tests/simulacao_historica_3_meses/reconcile.py` e `tests/homologacao_extrema/reconcile.py` passaram a baixar `export.xlsx` e conferir a planilha (resposta 200, arquivo Excel válido, acentos e linhas).

**Cards em cima, filtros embaixo.** A regra fica no `PageFrame`: quando a tela tem filtros e o conteúdo começa por uma grade de cards (`metric-grid`), essa grade sobe para cima da barra de filtros. Telas que passam `summary` usam o que passaram. Valeu para Análises, Produção (realizada, execução das OPs, planejado × realizado), Auditoria (eventos de status, confiabilidade, alertas), Rastreabilidade (lote/material/nesting) e Operações com filtro. Andon, TV e telas do operador não usam essa barra e não mudaram. A Tela inicial (Visão Geral) também não mudou: a grade arrastável de blocos é o próprio conteúdo, e subi-la jogaria os filtros para o fim da página.
