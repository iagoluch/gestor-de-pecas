# Todo número clicável — Fase 1 (Tempo + painel lateral + chat) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicar em qualquer número de tempo (sem demanda, parada planejada/não planejada, a esclarecer, produção, setup…) abre um painel lateral com a composição setor → recurso → trecho que fecha com o total, mais um chat com a IA que recebe essa mesma explicação.

**Architecture:** A consolidação de tempo físico (`mes/analytics/physical_time.py`) passa a carregar os ids dos eventos de origem e a regra aplicada em cada trecho. Um serviço novo monta a árvore de explicação **a partir da mesma consolidação** que gera o número (sem segunda fórmula). Um endpoint genérico `GET /api/v1/management/explicacao` devolve a árvore; um componente React único (painel lateral) a exibe; o chat reutiliza `AIService` recebendo uma referência da explicação (o servidor recalcula a árvore, não confia no cliente).

**Tech Stack:** Python 3 / FastAPI / Pydantic / Postgres (`eventos_estado_recurso`), React + TypeScript (Vitest), SSE da IA existente.

**Spec:** `docs/superpowers/specs/2026-10-16-explicacao-clicavel-design.md` (inventário: `...-inventario.md`). Leia o desenho antes: decisões 1–5 e seções 3.1, 4 e 6 são requisitos.

## Global Constraints

- **A Fase 1 só explica; não muda fórmula.** OEE, custo da Diretoria e digest do Telegram ficam com a conta de hoje. Se a explicação revelar conta errada, vira achado para o Iago, não correção silenciosa.
- Média por recurso = total ÷ recursos com turno/calendário no período; sempre mostrar "N recursos" (e "N recursos, D dias" em vários dias).
- Parada nunca solta: duas linhas "Parada planejada" e "Parada não planejada"; "A esclarecer" é terceira linha própria. Total = soma das linhas.
- Quando a lista de Análises > Paradas não bater com o consolidado, vale o consolidado; a lista ganha "diferença: X h, motivo: …".
- Painel respeita permissão: endpoint exige nível de gestão (`require_management_user`); nome/crachá do operador só nesse nível; operador de chão não ganha clique; telas de TV (Andon, Solda) sem clique nem painel.
- IA do chat responde **somente** com a explicação recebida; avisa quando a árvore foi truncada.
- Não tocar no trabalho em andamento no repositório (aba Diretoria, fila manual por área, `backend/api/dependencies/auth.py` e demais arquivos já modificados e não commitados). Commitar só os arquivos de cada tarefa.
- Dias passados: explicáveis a partir de `eventos_estado_recurso` (sem nova gravação). Painel mostra "calculado às HH:MM".
- Risco R3 (consolidação de tempo físico/OEE): owners `mes-domain-guardian`/`oee-engineer`; gates `qa-test-engineer` e `technical-reviewer`; `ai-llm-engineer` na Tarefa 6; `frontend-engineer` na Tarefa 5.
- Validação proporcional: rodar só os testes do que mudou (`pytest <arquivos>`, `npx vitest run <arquivo>`), não a suíte inteira.

## Review Focus

1. Trecho que cruza a borda do período (início antes do filtro, fim aberto "agora"): deve ser recortado e a soma continuar fechando.
2. Recurso com evento mas **sem** turno/calendário no período: não entra no divisor da média nem some do total; aparece só em "sem calendário" (sem esconder horas).
3. Períodos com vários dias: divisor = recursos distintos com calendário em algum dia; painel mostra "N recursos, D dias".
4. Fontes sobrepostas / conflito: trecho "a esclarecer" lista as fontes em conflito; reclassificação para "não planejada" mostra a regra aplicada.
5. Árvore grande: corte por tamanho com `truncated=true` e aviso na IA; usuário sem nível de gestão recebe 403 e nenhum dado.

---

## File Structure

- Modify `mes/analytics/physical_time.py` — carregar `source_refs` e `rule` nos trechos consolidados.
- Create `mes/services/metric_explanation.py` — `MetricExplanationService`: monta a árvore (total, filhos, trechos, excluídos, frase de regra, `calculated_at`, `reconciliation`).
- Modify `mes/services/management.py` — extrair a etapa de consolidação do `get_overview` para método reutilizável `physical_consolidation(filters)`; corrigir `resource_count`.
- Modify `mes/services/frontend_facade.py:251-288` — linhas de composição: Parada planejada/não planejada/a esclarecer, `resource_count` por calendário.
- Create `backend/api/schemas/explanation.py`, `backend/api/routers/explanation.py`; Modify `backend/api/main.py` (registrar router) — ⚠ arquivo já modificado e não commitado: adicionar só as 2 linhas de include e commitar com `git add -p`.
- Modify `backend/api/schemas/ai.py`, `backend/api/routers/ai.py`, `mes/services/ai_service.py` — referência de explicação na mensagem do chat.
- Create `web/src/components/MetricExplanationPanel.tsx`, `web/src/hooks/useMetricExplanation.ts`; Modify `web/src/types/api.ts` (⚠ já modificado: `git add -p`), `web/src/pages/ManagementOverviewPage.tsx`, `web/src/pages/operations/OperationsPages.tsx`.
- Tests: `tests/test_physical_time_provenance.py`, `tests/test_metric_explanation.py`, `tests/test_explanation_endpoint.py`, `tests/test_explanation_ai_context.py`, `web/src/test/metric-explanation-panel.test.tsx`.

---

### Task 1: Consolidado carrega origem e regra

**Files:**
- Modify: `mes/analytics/physical_time.py` (`PhysicalConsolidatedSegment`, `_sweep_resource`, `_resolve_stop_classification`)
- Test: `tests/test_physical_time_provenance.py`

**Interfaces:**
- Consumes: `PhysicalInputSegment(resource, sector, category, start, end, source_ref, stop_classification)`; `build_physical_state_inputs` (`mes/analytics/resource_state.py:66`) já preenche `source_ref="estado_recurso:<id>"`.
- Produces: `PhysicalConsolidatedSegment.source_refs: tuple[str | int, ...] = ()` e `.rule: Rule | None = None`, onde `Rule` é `Literal["production_prevailed", "state_conflict", "reclassified_to_unplanned"]`. Os campos novos têm default, então chamadores atuais não quebram. Totais e chaves de `consolidate_physical_time()` ficam idênticos.

- [ ] **Step 1: Teste que falha** — em `tests/test_physical_time_provenance.py`:
  - `test_single_source_keeps_ref`: um `PhysicalInputSegment` NO_DEMAND com `source_ref="estado_recurso:7"` → único segmento consolidado com `source_refs == ("estado_recurso:7",)` e `rule is None`.
  - `test_production_prevails_records_rule`: PRODUCTION e DOWNTIME sobrepostos → segmento PRODUCTION com ambos os refs e `rule == "production_prevailed"`.
  - `test_state_conflict_records_rule`: dois estados não produtivos diferentes sobrepostos → `category == UNKNOWN`, `state_conflict is True`, `rule == "state_conflict"`, refs das duas fontes.
  - `test_divergent_stop_classification_records_rule`: DOWNTIME planejada + DOWNTIME não planejada sobrepostas → `stop_classification == UNPLANNED`, `rule == "reclassified_to_unplanned"`.
  - `test_totals_unchanged`: o `consolidate_physical_time` dos 4 casos devolve os mesmos `totals` de antes (comparar com valores calculados à mão no teste).
- [ ] **Step 2:** `pytest tests/test_physical_time_provenance.py -v` → FAIL (campos inexistentes).
- [ ] **Step 3:** Implementar os dois campos e preenchê-los em `_sweep_resource` com os `source_ref` dos segmentos ativos no intervalo (sem `None`, ordenados) e a regra conforme a decisão tomada no intervalo.
- [ ] **Step 4:** `pytest tests/test_physical_time_provenance.py tests/test_resource_state_no_demand_and_break.py -v` → PASS.
- [ ] **Step 5:** Commit `feat(tempo): consolidado carrega origem e regra aplicada` (só os 2 arquivos).

---

### Task 2: Consolidação reutilizável + divisor da média por calendário

**Files:**
- Modify: `mes/services/management.py` (`get_overview` L55-729; entradas físicas L129-137 e L291-299, substituição canônica L197-209, consolidação L315/L367, `hours` L634-664)
- Test: `tests/test_metric_explanation.py` (primeira parte)

**Interfaces:**
- Consumes: `consolidate_physical_time`, `build_physical_state_inputs` (Tarefa 1 já carrega origem).
- Produces: `ManagementService.physical_consolidation(self, filters: AnalyticsFilter) -> dict` retornando `{"consolidated": <retorno de consolidate_physical_time>, "calendar_resources": set[str], "days": int, "calculated_at": datetime}`; `get_overview` passa a chamá-lo (mesmos números de hoje) e `hours["resource_count"]` = `len(calendar_resources)`, com `hours["day_count"]`.

- [ ] **Step 1: Testes que falham** em `tests/test_metric_explanation.py`:
  - `test_overview_numbers_unchanged_after_extraction`: com os fixtures do `tests/test_execution_to_management_consistency.py`, `hours.no_demand_seconds`, `downtime_seconds`, `planned_downtime_seconds` iguais antes/depois da extração (valores esperados lidos do overview atual, fixados no teste).
  - `test_resource_count_is_resources_with_calendar`: 3 recursos com eventos, 2 com turno → `hours["resource_count"] == 2`.
  - `test_multi_day_divisor_is_distinct_resources`: 2 dias, recurso A com turno no dia 1 e B no dia 2 → `resource_count == 2`, `day_count == 2`.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Extrair o método (mover, não duplicar) e ajustar o divisor. Confirmar na leitura do código se `NO_DEMAND` no overview vem só dos eventos gravados (spec seção 8); registrar a resposta num comentário curto do teste.
- [ ] **Step 4:** `pytest tests/test_metric_explanation.py tests/test_execution_to_management_consistency.py tests/test_management_overview_trend.py -v` → PASS.
- [ ] **Step 5:** Commit `refactor(tempo): consolidação reutilizável e divisor por calendário`.

---

### Task 3: Serviço de explicação de métrica de tempo

**Files:**
- Create: `mes/services/metric_explanation.py`
- Test: `tests/test_metric_explanation.py` (segunda parte)

**Interfaces:**
- Consumes: `ManagementService.physical_consolidation(filters)` (Tarefa 2); segmentos com `source_refs`/`rule` (Tarefa 1).
- Produces: `MetricExplanationService(management, repository)` com
  `explain(metric: str, filters: AnalyticsFilter, *, max_nodes: int = 400) -> ExplanationTree`.
  `ExplanationTree` (dataclass) = `{metric, label, total_seconds, average_seconds, resource_count, day_count, parent_total_seconds, siblings: list[{metric, label, seconds}], reason: str, rule: str, children: list[Node], excluded: list[{label, seconds, reason}], reconciliation: {ok: bool, sum_seconds, diff_seconds}, calculated_at: str, truncated: bool}`; `Node` = `{kind: "sector"|"resource"|"stretch", label, seconds, children, detail?: {start, end, who?, origin, record_id}}`.
  Métricas válidas: `tempo.producao`, `tempo.setup`, `tempo.sem_demanda`, `tempo.parada_planejada`, `tempo.parada_nao_planejada`, `tempo.a_esclarecer`, `tempo.fora_turno`; outra → `UnknownMetricError`.

- [ ] **Step 1: Testes que falham:**
  - `test_sem_demanda_tree_sums_to_total`: `reconciliation.ok is True` e `sum(setor.seconds) == total_seconds` e, por setor, `sum(recurso) == setor`.
  - `test_total_equals_overview_number`: `tree.total_seconds == overview["hours"]["no_demand_seconds"]` para cada métrica de tempo (garante "mesma conta").
  - `test_parada_two_lines_plus_a_esclarecer_sum`: planejada + não planejada + a esclarecer == total de parada consolidado.
  - `test_excluded_items_listed_with_reason`: intervalo de almoço (parada planejada) aparece em `excluded` de `tempo.sem_demanda` com `reason` não vazio.
  - `test_stretch_detail_has_origin_and_record_id`: trecho tem `detail.record_id` (do `source_ref`) e `origin`.
  - `test_unknown_metric_raises`.
  - `test_truncation_flag`: com `max_nodes=3` e 10 recursos → `truncated is True` e o total/fechamento continuam corretos (resto agrupado em "outros N recursos").
  - `test_empty_period`: sem trechos → total 0, `reconciliation.ok is True`, `reason` explica "nenhum registro no período".
  - `test_segment_crossing_period_boundary_is_clipped`.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implementar. Frase de `reason`/`rule` vem de um dicionário `RULE_TEXT` por métrica (textos em português simples da spec, seção 4). Para `tempo.sem_demanda`, "última OP encerrada no recurso e por quem" vem do repositório; se indisponível, omitir a frase em vez de inventar. `who` só preenchido quando houver dado do evento.
- [ ] **Step 4:** rodar a segunda parte + Tarefa 2 → PASS.
- [ ] **Step 5:** Commit `feat(explicacao): serviço de explicação das métricas de tempo`.

---

### Task 4: Endpoint com validação de nível no servidor

**Files:**
- Create: `backend/api/schemas/explanation.py`, `backend/api/routers/explanation.py`
- Modify: `backend/api/main.py` (só o include do router; `git add -p`)
- Test: `tests/test_explanation_endpoint.py`

**Interfaces:**
- Consumes: `MetricExplanationService.explain` (Tarefa 3); `require_management_user`; filtros do mesmo parser que `GET /management/inicio` usa (reutilizar, não reescrever).
- Produces: `GET /api/v1/management/explicacao?metric=<id>&<mesmos filtros de período/setor da Visão Geral>` → JSON com o `ExplanationTree`; `422` para métrica desconhecida; `403` sem nível de gestão.

- [ ] **Step 1: Testes que falham** (usar o client e fixtures de `tests/test_management_insights.py` / `test_user_management.py` como modelo):
  - `test_requires_management_level`: usuário operador → 403, corpo sem dados.
  - `test_returns_tree_for_management_user`: 200 e `children` não vazio.
  - `test_unknown_metric_422`.
  - `test_same_filters_same_total_as_inicio`: `total_seconds` igual ao `hours` de `/management/inicio` com os mesmos filtros.
- [ ] **Step 2:** rodar → FAIL. **Step 3:** implementar router + schema. **Step 4:** PASS. 
- [ ] **Step 5:** Commit `feat(explicacao): endpoint GET /management/explicacao`.

---

### Task 5: Rótulos da composição + painel lateral no frontend

**Files:**
- Modify: `mes/services/frontend_facade.py:251-288` (composição: Parada planejada, Parada não planejada, A esclarecer como linhas próprias; `metric` id em cada item; `resource_count`/`day_count` do calendário)
- Create: `web/src/components/MetricExplanationPanel.tsx`, `web/src/hooks/useMetricExplanation.ts`
- Modify: `web/src/types/api.ts` (tipos `ExplanationTree`/`ExplanationNode`; `git add -p`), `web/src/pages/ManagementOverviewPage.tsx` (Composição do tempo), `web/src/pages/operations/OperationsPages.tsx` (Operações > Tempo, `categoryTotal`/`categoryAverage`)
- Test: `tests/test_metric_explanation.py::test_time_composition_lines` e `web/src/test/metric-explanation-panel.test.tsx`

**Interfaces:**
- Consumes: endpoint da Tarefa 4; padrão de `web/src/components/ManagementInsightDrawer.tsx` (`useDialogFocus`, foco, fechar com Esc).
- Produces: `<MetricExplanationPanel metric: string; filters: OverviewFilters; onClose: () => void />`; cada item de `time_composition.items` ganha `metric: string`; a média sempre exibe `N recursos`.

- [ ] **Step 1: Testes que falham:**
  - Backend `test_time_composition_lines`: itens contêm "Parada planejada", "Parada não planejada" e "A esclarecer" separados, e a soma deles = parada consolidada.
  - Frontend `metric-explanation-panel.test.tsx`: (a) mostra número grande, linha "média … (N recursos)" e barra por setor; (b) clicar em setor expande recursos, clicar em recurso expande trechos, sem trocar de tela; (c) mostra "✓ os setores somam X" quando `reconciliation.ok` e aviso vermelho com a diferença quando não; (d) registro técnico (id/origem) só após clicar no trecho; (e) mostra "calculado às HH:MM"; (f) estado de erro 403/500 com mensagem simples; (g) `truncated` mostra aviso.
  - Teste de página: clicar em "Recurso sem demanda" na Visão Geral abre o painel com `metric="tempo.sem_demanda"`; em telas de TV (Andon) nenhum botão de explicação aparece.
- [ ] **Step 2:** `pytest tests/test_metric_explanation.py -k composition -v` e `cd web && npx vitest run src/test/metric-explanation-panel.test.tsx` → FAIL.
- [ ] **Step 3:** Implementar painel lateral (desliza por cima, sem rota/aba nova), hook de busca e fios nas duas telas. Visual: seguir `.superpowers/brainstorm/8930-1792171523/content/explicacao-simples.html` (simples: número grande, uma frase, barras).
- [ ] **Step 4:** testes PASS + `cd web && npx tsc --noEmit`.
- [ ] **Step 5: Prova visual** (exigência do Iago): subir o preview, abrir Visão Geral, clicar em "Recurso sem demanda", capturar tela (claro e escuro) e escrever a autocrítica "Eu fiz certo? Por quê?". Não commitar sem a prova.
- [ ] **Step 6:** Commit `feat(explicacao): painel lateral e linhas de composição do tempo`.

---

### Task 6: Chat com a IA dentro do painel

**Files:**
- Modify: `backend/api/schemas/ai.py` (`AIMessageRequest.explanation: ExplanationRef | None`), `backend/api/routers/ai.py:117-175`, `mes/services/ai_service.py` (`stream_message`, via `build_budgeted_context`)
- Modify: `web/src/components/MetricExplanationPanel.tsx` (área de chat reutilizando o streaming de `AssistantDock.tsx`/`AssistantMarkdown.tsx`)
- Test: `tests/test_explanation_ai_context.py`, estender `web/src/test/metric-explanation-panel.test.tsx`

**Interfaces:**
- Consumes: `MetricExplanationService.explain` (Tarefa 3); `AIService.stream_message(conversation_id, content, context, retry=False)`.
- Produces: `ExplanationRef = {metric: str, filters: <mesmo objeto da Tarefa 4>}`; o servidor recalcula a árvore (nunca aceita árvore do cliente) e injeta uma mensagem de sistema compacta com: total, composição, trechos, excluídos, regra e `truncated`. O chat só é aceito para nível de gestão (já garantido por `require_management_user`).

- [ ] **Step 1: Testes que falham:**
  - `test_context_contains_tree_values`: a lista de mensagens enviada ao provedor (provedor falso) contém o total e os nomes dos setores/recursos da árvore.
  - `test_system_instruction_restricts_to_explanation`: instrução manda responder só com esses dados, dizer "não sei" e apontar a Rastreabilidade da OP quando a pergunta fugir.
  - `test_truncated_tree_adds_warning_instruction`.
  - `test_client_cannot_inject_tree`: `explanation` aceita só `metric` + filtros (campo extra → 422, `extra="forbid"`).
  - `test_context_respects_token_budget`: árvore grande é reduzida (agrupa "outros N") sem estourar `request_token_budget`.
  - Frontend: digitar pergunta no painel envia `explanation={metric, filters}` e renderiza a resposta em streaming; erro 429 mostra "Limite temporário da IA" sem fechar o painel.
- [ ] **Step 2:** rodar → FAIL. **Step 3:** implementar (owner `ai-llm-engineer`). **Step 4:** PASS.
- [ ] **Step 5: Prova real:** com a chave configurada, perguntar no painel "por que o LASER1 está sem demanda?" e confirmar que a resposta cita horas/trechos da árvore. Sem chave, registrar que esta prova ficou pendente.
- [ ] **Step 6:** Commit `feat(explicacao): chat com IA recebe a explicação do painel`.

---

### Task 7: Análises > Paradas mostra a diferença para o consolidado

**Files:**
- Modify: serviço/rota que alimenta Análises > Paradas (localizar com `graphify query "Análises Paradas lista de eventos"`), `web/src/pages/` da tela correspondente
- Test: `tests/test_metric_explanation.py::test_stops_list_difference_line`

**Interfaces:**
- Consumes: totais de `tempo.parada_planejada` + `tempo.parada_nao_planejada` + `tempo.a_esclarecer` (Tarefa 3).
- Produces: campo `difference: {seconds: float, reason: str} | None` no payload da lista; a tela exibe "diferença: X h, motivo: …" quando `abs(seconds) > 0`; o total exibido de parada = consolidado.

- [ ] **Step 1:** teste: lista de eventos com sobreposição → `difference.seconds` = soma da lista − consolidado, com `reason` ("eventos sobrepostos contados uma vez") não vazio; sem diferença → `None`. Mais um teste de frontend (linha aparece/não aparece).
- [ ] **Step 2–4:** FAIL → implementar → PASS. **Step 5:** Commit `fix(paradas): lista mostra diferença para o consolidado`.

---

### Task 8: Fechamento (gates)

- [ ] **Step 1:** Rodar só o que mudou: `pytest tests/test_physical_time_provenance.py tests/test_metric_explanation.py tests/test_explanation_endpoint.py tests/test_explanation_ai_context.py tests/test_resource_state_no_demand_and_break.py tests/test_execution_to_management_consistency.py tests/test_management_overview_trend.py tests/test_management_insights.py -q` e `cd web && npx vitest run src/test/metric-explanation-panel.test.tsx && npx tsc --noEmit` → tudo verde.
- [ ] **Step 2: Teste-fecho da fase** `test_every_time_metric_list_sums_to_total` em `tests/test_metric_explanation.py`: para cada métrica válida, `reconciliation.ok` com dados dos fixtures de consistência (dia com produção, setup, parada planejada e não planejada, sem demanda, conflito).
- [ ] **Step 3:** `qa-test-engineer` tenta quebrar (sobreposições, fuso/virada de dia, evento aberto "agora", recurso sem calendário); `technical-reviewer` revisa o diff completo da fase contra o desenho. Corrigir o que apontarem.
- [ ] **Step 4:** Verificar que nenhum arquivo do trabalho em andamento (Diretoria, fila manual, auth) entrou nos commits: `git log --stat` dos commits da fase.
- [ ] **Step 5:** Atualizar o desenho (seção 8) com as respostas dos "pontos não conferidos" resolvidos e registrar na memória do projeto o estado da Fase 1.

---

## Fora desta fase (planos próprios depois)

- **Fase 2** — peças boas/refugo/retrabalho + trocar somas de 200 linhas por totais da API. Bloqueada por duas respostas do Iago (base do percentual; qual contagem de "aguardando inspeção").
- **Fase 3** — OEE e demais KPIs, custo da Diretoria (taxa de hoje com aviso), Corte, tempo padrão, integrações.
