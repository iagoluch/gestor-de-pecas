# Inventário de números calculados — Gestor de Peças

Somente leitura. Gerado em 16/10/2026. Raiz: `Gestor de Peças - Area de Testes`.
Legenda dos campos de cada bloco: **Tela** (onde aparece) · **API** · **Cálculo** (função e fórmula simples) · **Fonte** (tabela/evento e granularidade) · **Rastro** (o que existe de verdade para ligar o número a quem/quando/OP/recurso/motivo/id/origem) · **Detalhe** (já existe clique/explicação? sim/parcial/não) · **Lacuna** (o que não é guardado e impede explicar).
"(suposição)" = não conferi no código nesta sessão. "(linha não conferida)" = o arquivo é certo, a linha não.
Abreviações de arquivo: `OpPages` = `web/src/pages/operations/OperationsPages.tsx`; `AnPages` = `web/src/pages/analytics/AnalyticsPages.tsx`; `mgmt` = `mes/services/management.py`; `facade` = `mes/services/frontend_facade.py`; `phys` = `mes/services/physical_time.py`; `oee` = `mes/services/oee.py`.

---

## ÍNDICE (uma linha por métrica)

### A. Tempo / OEE (21)
| # | Métrica | Onde aparece | Resumo |
|---|---|---|---|
| T1 | Composição do tempo (horas por estado) | Visão Geral | Soma por estado dos segmentos físicos de todos os recursos |
| T2 | Cartões OEE / Disponibilidade / Performance / FTT | Visão Geral | `calculate_oee` sobre horas e peças do período |
| T3 | Recurso sem demanda (h, média, nº recursos) | Visão Geral e Operações > Tempo | Horas em que o recurso não tinha OP na fila; derivado, não gravado |
| T4 | Categorias de tempo (total e média) | Operações > Tempo | Soma por recurso da categoria ÷ nº de recursos da lista |
| T5 | Tempo produtivo / parado / total medido / a esclarecer | Operações > Tempo | Somas de `totals` por recurso; "a esclarecer" = estado conflitante |
| T6 | Fora de turno | Visão Geral e Operações > Tempo | União do calendário global menos o turno; não é somado por recurso |
| T7 | Parada (planejada x não planejada) | Visão Geral, Diretoria, Análises | `downtime_seconds`; Diretoria subtrai a planejada |
| T8 | "Média por recurso" | Várias telas | Total ÷ `by_resource.length` (divisor muda por tela) |
| T9 | Atividade sem OP | Visão Geral | Tempo em atividade diária / sem OP |
| T10 | Não identificado / estado conflitante | Visão Geral, Operações > Tempo | Segmentos com estados que se contradizem viram UNKNOWN |
| T11 | OEE detalhado (componentes, AE, produtividade, utilização, perdas) | Análises > OEE | A, P, FTT, OEE; perda = 100 − valor (p.p.) |
| T12 | Horas e utilização (físico, atribuído bruto, sobreposição removida) | Análises > Horas | Compara tempo físico x tempo atribuído a OP |
| T13 | Paradas e Setup (pareto por motivo) | Análises > Paradas e Setup | Soma de duração por motivo; lista por evento |
| T14 | Capacidade (utilização %) | Análises > Capacidade | Horas usadas ÷ horas com calendário |
| T15 | Confiabilidade (MTBF, MTTR, falhas) | Análises > Confiabilidade | Média entre quebras e tempo de reparo |
| T16 | Setores: produção/setup/paradas por setor + destaques | Tela inicial > Setores | Soma por setor de tempos do overview |
| T17 | Tempo físico e utilização nos relatórios | Relatórios > Indicadores/Perdas | Mesmo analytics, outro empacotamento |
| T18 | Relatório de tempos por setor / por mês | `operational_reports` (relatórios operacionais) | Tempo por OP com fonte rateio/timeline/igualitário |
| T19 | Disp./Perf./FTT do recurso | Andon (cartão do recurso) | `resource_kpis` casados por nome ou alias |
| T20 | Contagem de recursos por estado | Andon (resumo) | Conta recursos por `state.category` |
| T21 | Cronoanálise (tempo médio ponderado) | Análises > Cronoanálise | Média ponderada pelo nº de amostras |

### B. Produção e peças (8)
| # | Métrica | Onde | Resumo |
|---|---|---|---|
| P1 | Planejada / boa / atendida / saldo / % atendida | Produção > OPs | Soma no navegador das linhas da página (200) |
| P2 | Produção boa / refugo / retrabalho / taxa de refugo | Produção > Produção realizada | Eventos de quantidade por setor |
| P3 | Planejado x Realizado | Produção > Planejado x Realizado | Plano da OP x eventos de quantidade |
| P4 | Totais de OPs (boas, refugo, paradas, refugo %) | Operações > Ordens | Soma no navegador sobre 200 linhas |
| P5 | Produção por setor + nº de OPs | Tela inicial > Setores | `SectorSummary` do overview |
| P6 | Peças boas / perdas / eventos / nestings da OP | Rastreabilidade > OP | Soma das operações da OP |
| P7 | Relatório Gerencial e Produção | Relatórios | Reaproveita overview/production |
| P8 | Produzido (Diretoria) | Diretoria > Painel/Ficha | Boas lançadas no período (hoje/semana/mês) |

### C. Qualidade / refugo / retrabalho (9)
| # | Métrica | Onde | Resumo |
|---|---|---|---|
| Q1 | Qualidade (boa/refugo/retrabalho, FTT, motivos de refugo, por setor) | Análises > Qualidade | Eventos de quantidade + motivos |
| Q2 | FTT | Visão Geral/Análises/Andon/Relatórios | boa ÷ (boa + refugo + retrabalho) |
| Q3 | Aguardando / aprovadas / retrabalho / refugo | Tela Qualidade (operador) | `resumo_qualidade` conta peças inspecionadas |
| Q4 | Pendentes de inspeção (contador) | Qualidade / menu | `contar_pendentes_inspecao`, limite 1000 OPs |
| Q5 | Histórico de primeira peça | Análises > Qualidade | Lista com inspetor, crachá, notas |
| Q6 | Alertas internos (total, pendentes) | Tela inicial > Alertas | Contagem de `alertas_internos` |
| Q7 | Alertas gerenciais (críticos/erros/atenções/total) | Tela inicial > Alertas | Contagem por severidade |
| Q8 | Cotas de qualidade (medidas/aprovação) | Qualidade > cotas | (suposição) valores digitados, sem agregação |
| Q9 | Inconsistências (contagem) | Auditoria / Relatório analítico | Contagem das regras de auditoria |

### D. OP / fila / entrega (6)
| # | Métrica | Onde | Resumo |
|---|---|---|---|
| O1 | Fila manual da área (contagens) | Áreas (nova, não commitada) | (suposição) `manual_queue.py` |
| O2 | Atraso / prazo de entrega / status por limite | Relatórios de setor, Produção | `prazo_entrega` x agora; limites em `operational_reports.py:12` |
| O3 | OPs ativas no Andon (máx. 6) | Andon | Corta em `MAX_ANDON_ACTIVE_OPS = 6` |
| O4 | OPs paradas | Operações > Ordens | Contagem no navegador |
| O5 | Fila sem demanda (`sem_demanda`) | Andon / Visão Geral | Recurso sem OP na fila |
| O6 | Chamadas não vistas (sininho) | Menu | Chamadas com id > última vista |

### E. Andon / mapa (5)
A1 Resumo por estado · A2 KPIs do recurso · A3 Mapa da fábrica (setores da planta) · A4 Turno atual (sempre "não configurado") · A5 Cor do cartão (status).

### F. Corte / SigmaNEST (5)
C1 Tempos de nesting (previsto/real/real do período/desvio) · C2 Dashboard do mês do Corte · C3 Planos (chapas total/cortadas/em corte/aguardando) · C4 Agrupamento por tarefa (nesting_count, concluídos, tempo real) · C5 Destaque (suposição).

### G. Custo / Diretoria (9)
D1 Produzido · D2 Horas paradas · D3 Custo das paradas · D4 Eficiência · D5 Trabalhou / disponível · D6 Parado (ficha) · D7 Custo do trabalho · D8 Custo por setor/recurso · D9 Valor da hora cadastrado.

### H. Tempo padrão (6)
S1 Padrão Protheus · S2 Manual · S3 Estimado (P25) · S4 Fonte em uso · S5 Resumo do recálculo · S6 Padrão x real (Análises).

### I. Integrações (4)
I1 Outbox por status · I2 Item mais antigo e idade · I3 Última falha · I4 Contadores de sincronização/pull (suposição).

### J. IA / Insights (4)
IA1 Evidência da IA · IA2 Explicações dos 4 KPIs · IA3 Exceções · IA4 Resultado das ferramentas (tools).

### K. Outros (5)
X1 Relatórios (5 tipos) · X2 Exportação Excel · X3 Digest do Telegram (suposição) · X4 Metas (suposição) · X5 Contadores/badges do menu.

**Total: 82 métricas.**

---

# BLOCOS POR ASSUNTO

## A. TEMPO / OEE

**T1 Composição do tempo** — Tela: Visão Geral > "Composição do tempo" (`ManagementOverviewPage.tsx`, linha não conferida). API: `/api/v1/management/overview`, campo `time_composition` montado em `facade` (~L243–311). Cálculo: `mgmt.get_overview` (L55–729; horas L634–664) varre cada recurso, une intervalos e soma segundos por estado (produção, setup, parada, retrabalho, sem OP, sem demanda, fora de turno, não identificado). Fonte: `eventos_estado_recurso` (estado físico), `fila` (para sem demanda), calendário. Rastro: no nível do segmento, só recurso + início/fim + estado; `consolidate_physical_time` (`phys`) perde o `source_ref` ao unir. Detalhe: parcial — só o cartão de KPI tem `ManagementInsightDrawer`; a composição não tem clique. Lacuna: não existe "linha de segmento" por recurso exposta; impossível dizer qual evento gerou cada hora.

**T2 KPIs OEE/Disp/Perf/FTT** — Tela: Visão Geral (4 cartões). API: overview `kpis`. Cálculo: `oee.calculate_oee`: A = trabalhado ÷ disponível (disponível = trabalhado + parada + desconhecido); P = (tempo padrão de execução + apoio) ÷ trabalhado; FTT = boas ÷ (boas+refugo+retrabalho); OEE = A×P×FTT/10000. Parada planejada sai da base. Período todo sem demanda → 100/0/0. `OEE_RULE_VERSION="corporativa-2026-09-24"`. Fonte: horas consolidadas + `eventos_quantidade_producao` + padrão de tempo. Rastro: versão da regra; parcelas A/P/FTT. Detalhe: SIM — `insights.kpi_explanations` (`management_insights.py`) + `ManagementInsightDrawer`; é o único mecanismo de explicação que existe. Lacuna: explicação mostra fórmula e valores agregados, não as OPs/eventos que compõem P (tempo padrão por OP) nem as horas por recurso. P > 100% não é limitado.

**T3 Recurso sem demanda** — Tela: Visão Geral ("509,6 h, média 13,4 h, 38 recursos") e Operações > Tempo ("Sem Demanda 13h25m média / 510h17m total"). API: overview `totals[NO_DEMAND]`; `/api/v1/operations/time`. Cálculo: soma de `totals[NO_DEMAND]` de todos os recursos; média = total ÷ nº de recursos (`OpPages` L212–266: `categoryTotal`, `categoryAverage`). NO_DEMAND é derivado: recurso sem OP na `fila` naquele intervalo (`resource_state.py`; Andon usa `item.sem_demanda`, `andon.py:663`). Fonte: NÃO existe no banco; é calculado a partir da ausência de OP na fila. Rastro: nenhum por hora; só o recurso e o intervalo calculado. Detalhe: não. Lacuna: não há registro "quando a fila ficou vazia", nem quem programou/removeu a OP; fila histórica não é guardada como série (suposição — conferir se há snapshot da fila). Este é o caso-exemplo do pedido: as 500 h não têm origem rastreável por evento.

**T4 Categorias de tempo** — Tela: Operações > Tempo (`OpPages` L252–261). API: `/api/v1/operations/time`. Cálculo: `categoryTotal(key)`: para fora_turno usa `data.totals.fora_turno`; para as demais soma `by_resource[].key`. `categoryAverage` = total ÷ `resourceCount` (= `by_resource.length`), exceto fora_turno que não tem média. Fonte: mesmo consolidado físico. Rastro: tabela por recurso. Detalhe: parcial (tabela por recurso, sem causa). Lacuna: o divisor é "quantos recursos aparecem na lista", não "quantos tinham calendário"; muda conforme filtro.

**T5 Cartões de tempo** — Tela: Operações > Tempo. Cálculo: Produtivo = produção+setup; Parado; Total medido; "A esclarecer" = `conflicting_state_seconds`. Fonte/rastro como T1. Detalhe: não. Lacuna: "a esclarecer" não lista quais intervalos conflitam nem entre quais estados.

**T6 Fora de turno** — Cálculo: união do calendário global (turnos/pausas) menos o que está em turno; não soma por recurso e não tem média (decisão 28/09). Fonte: tabelas de calendário (`calendar`, ShiftsPage/PausesPage; vigência migration 50). Rastro: turno e pausa cadastrados. Detalhe: não. Lacuna: hora fora de turno de um recurso específico não é explicável por recurso (é global).

**T7 Parada planejada x não planejada** — Cálculo: `downtime_seconds` do consolidado; planejada = `planned_downtime_seconds`. Diretoria usa `_unplanned_stop_hours` (`director_summary.py:520`) = parada − planejada. Classificações diferentes na mesma janela viram UNPLANNED (`phys`). Fonte: `eventos_estado_recurso` com motivo de parada. Rastro: motivo (por evento), recurso, início/fim; `estado_recurso_id` aparece na tabela de Análises > Paradas. Detalhe: parcial (Análises lista paradas por evento com link da OP). Lacuna: o número de "Parada" da Visão Geral soma o consolidado, que pode não bater com a soma da lista de eventos (sobreposição e prevalência da produção).

**T8 Média por recurso** — Telas: Visão Geral, Operações > Tempo, Relatórios (`formatAveragePerResource(total, rows.length)`), Análises > Horas (`by_resource.length`), Capacidade (`recursos_com_calendario`). Lacuna: três divisores diferentes para a mesma frase "média por recurso".

**T9 Atividade sem OP** — Cálculo: tempo em estado de atividade sem OP vinculada (atividade diária). Fonte: `apontamentos_operacionais`/eventos de operador. Rastro: operador e recurso (suposição para granularidade). Detalhe: não.

**T10 Não identificado / conflitante** — Cálculo: estados que se contradizem no mesmo instante e recurso viram UNKNOWN (`phys`). Entra no denominador de disponibilidade. Detalhe: não. Lacuna: o conflito perde os eventos de origem.

**T11 OEE (Análises)** — Tela: Análises > OEE (`AnPages`). API: `/api/v1/analytics/oee`. Campos: componentes, `extended_metrics` (AE, produtividade, utilização), evolução, `losses_breakdown`; `lossLabel` = 100 − valor em p.p. Serviço: `IndustrialAnalyticsService` (`industrial_analytics.py`). Detalhe: parcial (gráficos). Lacuna: evolução e perdas não ligam a OPs ou eventos.

**T12 Horas e utilização** — API: `/analytics/hours-utilization`. Campos: `physical_seconds`, `raw_attributed_timeline_seconds`, `overlap_removed_seconds`, utilização vem de simulação. Lacuna: "sobreposição removida" é um total; não diz quais OPs/recursos se sobrepuseram.

**T13 Paradas & Setup** — API: `/analytics/downtimes|setups`. Pareto por motivo; tabela por evento com link da OP. Rastro: SIM é o mais rastreável (evento, OP, recurso, motivo, início/fim). Detalhe: sim (lista). Lacuna: operador que registrou a parada (suposição: está em `eventos_apontamento_operador`, não exibido).

**T14 Capacidade** — API: `/analytics/capacity`. Divisor `recursos_com_calendario`. Detalhe: não.

**T15 Confiabilidade** — API: `/analytics/reliability`: MTBF, MTTR, falhas, por recurso, motivos. Fonte: paradas classificadas como quebra. Lacuna: o que conta como "quebra" é definido por classificação do motivo, não visível na tela.

**T16 Setores** — Tela: Tela inicial > Setores (`HomePages.tsx` L62–103). API `/api/v1/management/sectors`: `items` + `highlights` (campos `tempo_producao_segundos`, `tempo_setup_segundos`, `tempo_parada_segundos`, `producao_boa`, `refugo`, `retrabalho`, `ops`). Detalhe: parcial (link para recursos do setor). Lacuna: destaques ("maior X") sem mostrar o critério/janela.

**T17 Relatórios de indicadores/perdas** — `ReportsPages.tsx`: "Tempo físico" e média (`formatAveragePerResource`); "Tempo de parada" por motivo. Mesma origem de Análises. Detalhe: não.

**T18 Relatório de tempos (setor/mês)** — `operational_reports.py`: `calcular_relatorio_tempos_setor` (L163) com fonte por OP `rateio | timeline_op | timeline_op_rateio_igualitario | dados_insuficientes`; `indicadores` (L336, chaves estranhas); `calcular_relatorio_tempos_mes` (L353) usa histórico de movimentação. Rastro: sim, a fonte do tempo é declarada por OP. Lacuna: o rateio igualitário é uma estimativa; não aparece na tela como aviso.

**T19 Disp./Perf./FTT do Andon** — `AndonPage.tsx` (`MetricLine`, L95, L189–191). `andon.py:747` `_apply_resource_metrics` casa `resource_kpis` do overview por nome exato ou alias. Lacuna: se o nome não casar, o recurso fica sem KPI (silencioso).

**T20 Resumo do Andon por estado** — `andon.py` `build_snapshot` L158–418: conta por `state.category`; KPIs gerais de `overview.kpis`. `current_shift` sempre NOT_CONFIGURED.

**T21 Cronoanálise** — API `/analytics/chronoanalysis`; média ponderada pelas amostras. Detalhe: não lista as amostras.

## B. PRODUÇÃO E PEÇAS

**P1 Produção > Ordens** — `ProductionPages.tsx` L50–110. API `/api/v1/orders?...page_size=200`. Cálculo: cartões somam NO NAVEGADOR as linhas recebidas (planejada, boa, refugo, atendida = boa+refugo, saldo = planejada − boa − refugo, mínimo 0). "Ordens no filtro" usa `page.total`. "% do planejado (só boas)" no cartão x "% atendida (boa+refugo)" na coluna. Fonte: apontamento + `eventos_quantidade_producao`. Rastro: link para Rastreabilidade da OP; linha por `apontamento_id`. Detalhe: parcial. Lacuna: acima de 200 OPs os cartões somam só parte e dizem "do filtro".

**P2 Produção realizada** — L112–158. API `/api/v1/orders/production`: `production.{good,scrap,rework,resources,availability,reason}`, `sectors[]`. Taxa de refugo = refugo ÷ (boa+refugo), calculada no navegador. Disponibilidade `sem_registros` mostra texto em vez de zero. Detalhe: não.

**P3 Planejado x Realizado** — L160–210. API `/orders/planned-vs-actual` (200 linhas). Soma no navegador; "Perdas" = refugo+retrabalho; "Atendimento" = (boa+refugo) ÷ planejada. Datas planejadas: `planning_dates.availability`. Lacuna: mesmo corte de 200.

**P4 Operações > Ordens** — `OpPages` L159–187. Totais (boas, refugo, OPs paradas) e refugo % = refugo ÷ (boa+refugo) calculados no navegador sobre 200 linhas.

**P5 Setores** — ver T16.

**P6 Rastreabilidade da OP** — `TraceabilityPages.tsx` L66–69, L113–120: "Peças boas" `trace.good`, "Perdas" = refugo+retrabalho, eventos = `timeline.length`, nestings vinculados. Rastro: o melhor do sistema — data/hora, recurso, operação, evento, status, operador, quantidade. Detalhe: SIM (é a tela de detalhe por OP). Lacuna: só por OP; não há caminho "do total para as OPs".

**P7 Relatórios Gerencial/Produção** — `ReportsPages.tsx`: mesmas fontes do overview; "Tempo produtivo" por setor (`tempo_produtivo_segundos`). Detalhe: não.

**P8 Produzido (Diretoria)** — ver D1.

## C. QUALIDADE / REFUGO / RETRABALHO

**Q1 Análises > Qualidade** — API `/analytics/quality`: totais boa/refugo/retrabalho, `ftt`, `scrap_reasons`, `by_sector`. Rastro: motivo de refugo; setor. Detalhe: parcial.

**Q2 FTT** — boa ÷ (boa+refugo+retrabalho); mesmo cálculo em `oee`; Andon e Relatórios reutilizam. Atenção: no `quality.py` `_finalizar` (L845) a inspeção posta quantidades via `OperatorFlowService`, então o FTT depende do que a inspeção classificou.

**Q3 Tela Qualidade (operador)** — `QualityPage.tsx` L12–16: 4 cartões. `quality.py` `resumo` L255; `quality_repository.py` L917: aguardando = Σ max(quantidade_total − peças registradas, 0) por inspeção; aprovadas/retrabalho/refugo = contagem de peças por resultado. Filtros por setor (sempre Qualidade) e setor de origem (SQL por roteiro). Rastro: `qualidade_pecas_inspecionadas` (peça a peça). Detalhe: sim (histórico da Qualidade, L283).

**Q4 Pendentes de inspeção** — `contar_pendentes_inspecao` (L957): soma (quantidade − registradas) nas OPs elegíveis, `limite=1000`. `resumo` usa esse valor para "aguardando". Armadilha: duas definições de "aguardando" (Q3 SQL vs. elegíveis), e o corte de 1000.

**Q5 Primeira peça** — `AnPages` `FirstPieceHistorySection`, API `/api/v1/management/first-pieces`: inspetor, crachá, notas. Rastro: bom.

**Q6 Alertas internos** — `HomePages.tsx` L52–56, L137–162; API `/management/internal-alerts` (`items`, `count`, `pending`); `first_piece_repository.py:633` `resumo_alertas_internos` agrupa por tipo/destinatário/severidade/status (COUNT e Σ quantidade). Rastro: OP, setor, recurso, destinatário, status de notificação. Detalhe: sim (tabela).

**Q7 Alertas gerenciais** — API `/management/alerts`: `by_severity`, `count`, `reliability_percentage` (pode ser nulo), `reliability_reason`. Cartões usam `critico`, `erro`, `aviso`. Lacuna: "total" não explica quais regras geram os alertas (suposição: vêm de `management_insights.exceptions`, limite 12 — conferir).

**Q8 Cotas** — (suposição) sem agregação; valores digitados e aprovados na inspeção (decisão 06/10).

**Q9 Inconsistências** — `AuditPages.tsx` (não lido) e Relatório analítico (`audit.count`). (suposição) contagem de regras de auditoria.

## D. OP / FILA / ENTREGA

**O1 Fila manual** — `mes/services/manual_queue.py`, `AreaQueuePanel.tsx` (arquivos novos, não commitados; não lidos a fundo). (suposição)

**O2 Atraso/entrega** — `prazo_entrega` (campo em `PlanActualRow`), status por limites `operational_reports.py:12`. Detalhe: não. Lacuna: não vi onde "atrasada" é calculada para a Visão Geral (suposição).

**O3 Limite de 6 OPs no Andon** — `andon.py` `MAX_ANDON_ACTIVE_OPS = 6`: lista truncada, sem aviso na tela (suposição sobre a tela).

**O4 OPs paradas** — contagem no navegador (P4).

**O5 Sem demanda** — ver T3.

**O6 Chamadas não vistas** — `chamada_repository.py:209`: COUNT de `chamadas` com id > `ultima_chamada_vista_id` do usuário (sem linha = tudo conta). Detalhe: sim (tela de Chamadas).

## E. ANDON / MAPA

**A1** resumo por estado — T20. **A2** KPIs — T19. **A3** Mapa da fábrica: `andon.py` `_plant_sectors` L420; blocos por setor da planta (Expedição=Almox, Projetos=Ferramentaria, Robô sem bloco próprio — memória 14/09). **A4** Turno: sempre NOT_CONFIGURED. **A5** Cor/status do cartão: derivado de `state.category` + `_apply_operational_state` (L663). Lacuna: cores não têm legenda com a regra numérica.

## F. CORTE / SIGMANEST

**C1** `cut.py` `listar_tempos_nesting` L418: `previsto`, `real`, `real_periodo`, `desvio`. Fonte: `apontamentos_corte` + tempos de nesting do SigmaNEST. Rastro: tarefa/plano/nesting.
**C2** `calcular_dashboard_mes` L475–547: bases misturadas (parte por período, parte acumulada) — conferir antes de comparar com C1.
**C3** `_build_plans` L726: `chapas_total/cortadas/em_corte/aguardando`, `tempo_previsto`, `tempo_real`.
**C4** `_group_rows` L818: `nesting_count`, `nestings_concluidos`, `nesting_atual`, `quantidade_chapas`, `tempo_real` = soma por nesting.
**C5** Destaque (`HighlightPage.tsx`): só tarefas liberadas pelo Corte; sem agregados lidos (suposição).
Lacuna geral: Corte não tem tempo padrão (S), então não entra na Performance como os demais.

## G. CUSTO / DIRETORIA

Janelas: `resolve_period` (`director_summary.py:48`): hoje, semana (segunda), mês (dia 1); fim = fim de hoje.
**D1 Produzido** — `DirectorPanel.tsx` L22; boas lançadas no período.
**D2 Horas paradas** — L23; só paradas não planejadas (`_unplanned_stop_hours`, L520).
**D3 Custo das paradas** — `costs` L248–281 / `stop_cost`; horas de parada x valor da hora do recurso e dos operadores; `_Context` L307–496 (`stop_slices`, `work_slices`, `assignments`, `people`, `_rates`).
**D4 Eficiência** — L30; "o mesmo OEE da Visão Geral" (mesmo `calculate_oee`, mas na janela da Diretoria).
**D5 Trabalhou/disponível** — `DirectorSheet.tsx` L64 (`trabalhou_h`, `disponivel_h`).
**D6 Parado (ficha)** — L66; por motivo (`reasons`).
**D7 Custo do trabalho** — L72; `work_cost`.
**D8 Custo por setor/recurso** — `panel` L126–174; `sheet` L177–231.
**D9 Valor da hora** — `DirectorCosts.tsx`: taxas por recurso e por operador (cadastro manual).
Rastro: parcial — a ficha mostra por setor/recurso; a regra "participação do operador com início mais recente vence" decide quem paga a parada. Detalhe: sim (ficha por setor); não há detalhe até o evento. Lacuna: histórico de valor da hora não é versionado (suposição — conferir se `CostRates` guarda vigência); custo usa a taxa atual.

**Lote 4 entregue (20/10/2026):** D1–D9 clicáveis via `GET /api/v1/diretoria/explicacao` (`dir.*`, só admin/diretoria; `/management/explicacao` recusa `dir.*`). Linha de motivo na Ficha abre só aquele motivo (`motivo=`); setor casa sem diferenciar maiúscula. Limites conhecidos: (1) valor da hora não é versionado — o custo usa a taxa atual (confirmado na explicação de D9); (2) pessoa sem crachá aparece como "Cadastrado" na tela de Custos mas a explicação diz "não cadastrado" — divergência só de texto, valor correto.

**Lote 5 entregue (20/10/2026):** só C1 ficou clicável — os 4 cartões de Rastreabilidade > Lote / Material / Nesting (`cut.nestings`, `cut.previsto`, `cut.realizado`, `cut.desvio`; árvore Máquina > Tarefa > Plano > Nesting). `/traceability/nestings` passou a devolver `totals` (soma de TODOS os itens do filtro, não só da página). Cartões só clicam com a busca vazia e sem carregamento (senão o número da tela e o explicado divergem). **Não feitos, de propósito:** C2 (`calcular_dashboard_mes`) não tem tela, só teste; C3/C4/C5 ficam em telas de operador/Destaque (regra: sem novo alvo de clique ali). Limite conhecido: nesting ainda cortando usa "agora", então a explicação pode diferir do cartão por segundos.

## H. TEMPO PADRÃO

`standard_time.py` (350 linhas) e `StandardTimePage.tsx`.
**S1** Protheus (oficial, por produto/operação/recurso) — não editável (409, `set_manual` L189).
**S2** Manual — versionado por `vigente_desde`; histórico com quem/quando (`StandardTimePage.tsx` L539–554). Rastro: bom. Corte não aceita manual.
**S3** Estimado — P25 das execuções, amostra mínima, janela de histórico, blocos de 14 dias (`_recalculate` L281).
**S4** Fonte em uso (`fonte_efetiva`): protheus, manual, estimado ou sem padrão.
**S5** Resumo do recálculo: `execucoes_elegiveis`, `chaves_avaliadas`, `chaves_estimadas`.
**S6** Padrão x real (Análises): soma só as linhas que têm esperado E real — exclui o resto em silêncio.
Lacuna: o estimado mostra detalhe curto (L411), mas não lista as execuções que entraram na amostra.

## I. INTEGRAÇÕES

`totvs_outbox_admin.py:40` `metrics` → `totvs_outbox_repository.py:579` `metricas_outbound_totvs`:
**I1** por status: total e máximo de tentativas (`totvs_outbox` GROUP BY status).
**I2** item mais antigo pendente/retry/enviando e idade em segundos.
**I3** última falha (código, mensagem, classe de entrega).
Rastro: bom — tentativas por item (`listar_tentativas_outbound_totvs`), chave de idempotência, payload.
**I4** contadores de pull/sync (Etapa 7B): (suposição) não lidos.

## J. IA / INSIGHTS

Ver seção de inconsistências 8. **IA1** evidência `[:50]` por lista; **IA2** `kpi_explanations`; **IA3** `exceptions[:12]`; **IA4** `ai_tools.py` (`TOOL_REGISTRY` L83, `_factory_projection` L546, `_kpi_explanation_projection` L675), 100 itens por lista, 10.000 caracteres por resultado, escolha de ferramenta por palavras-chave.

## K. OUTROS

**X1** Relatórios: 5 tipos (`gerencial`, `producao`, `perdas`, `indicadores`, `dados_analiticos`) — `ReportsPages.tsx`. Cada um reaproveita overview/analytics.
**X2** Exportação `.xlsx` por `/api/v1/reports/{tipo}/export.xlsx` (workbook em `api/report_workbook/executive.py`, `build_indicadores` L1036; reserva fechada com os números do arquivo em `report_repository.py:106`). Lacuna: Excel e tela usam o mesmo filtro, mas não há garantia gravada de que os números são idênticos (suposição).
**X3** Digest do Telegram (`telegram_digest.py`) — não lido (suposição).
**X4** Metas (`GoalsPage.tsx`) — não lida (suposição).
**X5** Contadores do menu: chamadas (O6), pendentes de inspeção (Q4), alertas internos pendentes (Q6).

---

# INCONSISTÊNCIAS E ARMADILHAS

1. **Sem demanda é inventado a partir de ausência.** NO_DEMAND = "não havia OP na fila" (T3). Não é evento, não tem id, não tem autor. 509,6 h na Visão Geral e 510h17m em Operações > Tempo vêm do mesmo total, mas a média muda (13,4 h x 13h25m — o mesmo valor em formatos diferentes, divisão por 38 recursos).
2. **O consolidado destrói a origem.** `consolidate_physical_time` une intervalos, deixa a produção prevalecer, converte conflitos em UNKNOWN e paradas de classes diferentes em UNPLANNED, e perde o `source_ref`. A soma da Visão Geral nunca bate item a item com a lista de eventos de Análises > Paradas.
3. **"Média por recurso" tem três divisores:** `by_resource.length` (Operações, Relatórios, Análises > Horas), `recursos_com_calendario` (Capacidade) e o nº de recursos do overview. Fora de turno não tem média.
4. **"Parada" tem várias definições:** consolidado total (Visão Geral), menos planejada (Diretoria `_unplanned_stop_hours`), soma da lista de eventos (Análises), e arredondamento de exibição ("26h36m" x "26,6 h").
5. **Totais somados no navegador sobre 200 linhas** (Produção > OPs, Planejado x Realizado, Operações > Ordens), enquanto "Ordens no filtro" usa o total real da API. Acima de 200 OPs os cartões subcontam sem aviso.
6. **Bases de percentual diferentes na mesma tela:** "% do planejado (só boas)" no cartão x "% atendida (boa+refugo)" na tabela; saldo ignora retrabalho; refugo % = refugo ÷ (boa+refugo) sem retrabalho, enquanto FTT inclui retrabalho no denominador.
7. **Exclusões silenciosas:** padrão x real soma só linhas com esperado e real; Corte não tem padrão; recurso sem KPI se o nome do Andon não casa; Andon mostra no máximo 6 OPs; pendentes de inspeção olham só 1000 OPs; listas da IA cortam em 50/12/100.
8. **A IA Industrial só vê totais.** `ManagementInsightsService` monta evidência com `[:50]` e exceções `[:12]`; `AIToolRegistry` (`ai_tools.py`) devolve projeções (`_factory_projection` L546, `_kpi_explanation_projection` L675) com 100 itens por lista e 10.000 caracteres por resultado, escolhidas por palavra-chave. A projeção de fábrica leva os totais do overview (inclusive `totals[NO_DEMAND]`), mas não os segmentos nem as OPs por trás — nada no consolidado guarda isso (ver 2). Por isso ela pode repetir "510 h sem demanda" e não consegue dizer quais recursos/dias.
9. **Janelas de tempo diferentes:** filtro global de gestão x Diretoria (hoje/semana/mês com fim = fim de hoje) x Andon (tempo real) x Corte (C2 mistura base de período e acumulada). "Eficiência" da Diretoria diz ser "o mesmo OEE da Visão Geral" mas só bate se o período escolhido for igual.
10. **Duas definições de "aguardando inspeção":** `resumo_qualidade` (peças das inspeções abertas) x `contar_pendentes_inspecao` (OPs elegíveis, limite 1000). `resumo` do `quality.py` (L255) junta as duas.
11. **Performance não é limitada a 100%** e período inteiro sem demanda vira 100/0/0: OEE pode parecer ótimo ou estranho sem aviso.
12. **Explicação só para 4 cartões.** Nenhuma outra métrica (inclusive Composição do tempo e Categorias de tempo) tem clique de explicação; faltam um identificador estável por número ("metric id") e uma lista de "itens que compõem" (recurso/dia/evento/OP).
13. **Custo usa a taxa atual** (suposição) e a regra "operador com início mais recente vence" decide quem carrega a parada; não é visível na tela.
14. **Rateio igualitário de tempo por OP** (T18) é estimativa e não é sinalizada como tal na tela (suposição sobre a tela).

## O que falta guardar para a explicação literal
- Série histórica da fila por recurso (para NO_DEMAND ter origem).
- Segmentos consolidados com a lista de `source_ref`/ids dos eventos que os formaram (e a regra aplicada: produção prevaleceu, conflito, reclassificação).
- Operador/crachá e origem (manual/automático/TOTVS) no segmento de parada exposto.
- Identificador estável por métrica + endpoint genérico "componentes da métrica" para o clique.
- Versão da taxa de custo por vigência.
- Amostras que entraram no tempo estimado.
