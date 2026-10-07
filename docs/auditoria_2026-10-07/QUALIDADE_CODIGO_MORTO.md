# Qualidade: código morto e duplicação (2026-10-07)

Escopo: `backend/`, `mes/`, `app/`, `web/src/`, `scripts/`. Somente leitura, exceto este arquivo. Não foi alterado nenhum código.

## Ferramentas

| Passo | Ferramenta | Resultado |
|---|---|---|
| 1 Python | `vulture` | NÃO RODADO: módulo não instalado (`No module named vulture`). Não foi instalado nada. |
| 1 Python (substituto) | `pyflakes` (já instalado) | 2 avisos F841 no escopo (ver abaixo). Sem F401 (import não usado). |
| 2 TypeScript | `web/node_modules/.bin/tsc --noEmit --noUnusedLocals --noUnusedParameters -p web/tsconfig.app.json` | 4 erros TS6133. Nenhum TS6196. |
| 3 Exports TS | Contagem de referências por símbolo (TypeScript API, `web/tsconfig.app.json`) | 309 exports; 56 sem nenhum uso fora do próprio arquivo. |
| 4 Python | Varredura AST própria + grep de repo inteiro | 158 candidatos a definição e 17 módulos; confirmados por grep. |
| 5 Duplicação | Corpos idênticos (AST Python; TS normalizado) | 5 grupos Python e 2 grupos TS. |

## Classificação

### SEGURO REMOVER (zero referências em todo o repo)

| Local | Nome | Evidência |
|---|---|---|
| `web/src/utils/systemState.ts:273` | `reportedValueText` | Sem export e sem uso externo; 1 ocorrência no repo inteiro (a definição). Passou no TS (0 ext, 1 interna). |
| `app/core/operator_sectors.py:318` | `is_operator_level` | `grep -rw` no repo inteiro: 1 ocorrência (a definição). |
| `app/core/paths.py:13` | `resource_path` | 1 ocorrência no repo inteiro. Verificar se não é usado por spec/instalador externo ao repo antes de apagar (a grep cobriu todos os arquivos do repo). |
| `app/core/paths.py:25` | `ensure_data_dir` | 1 ocorrência no repo inteiro. Mesma ressalva de `resource_path`. |

Ressalva: `reportedValueText` e os 3 Python estão sem uso em código, testes, docs e config. Ainda assim, quem apagar deve rodar o teste do módulo afetado.

### TS6133 (variáveis e imports não usados, confirmados pelo tsc)

| Local | Nome | Classe |
|---|---|---|
| `web/src/pages/home/ChamadasContatosPage.tsx:3` | `useAuth` (import) | SEGURO REMOVER (import sem uso) |
| `web/src/pages/production/ProductionPages.tsx:15` | `formatHours` (import) | SEGURO REMOVER (a função continua em uso em 7 outros arquivos; só o import sobra) |
| `web/src/system/ReferenceClock.tsx:1` | `useMemo` (import) | SEGURO REMOVER (import sem uso) |
| `web/src/test/operator.test.tsx:684` | `calls` (variável) | SEGURO REMOVER (variável de teste sem uso; é teste, mas não afeta o comportamento) |

### PROVÁVEL MORTO (só referenciado por teste ou doc)

| Local | Nome | Evidência |
|---|---|---|
| `mes/analytics/resource_state.py:91` | `summarize_physical_states` | Só em `tests/test_resource_state_no_demand_and_break.py` (2 ocorrências no teste). Sem uso em código de produção. |
| `mes/services/corporate_integration.py:6` | `PendingCorporateIntegration` | Só em `tests/test_corporate_integration.py`. Confirmar com o dono antes de remover, porque é classe de integração corporativa. |

### NÃO MEXER / ESCALAR (uso dinâmico, contrato, auth, integração, regra de negócio)

| Local | Nome | Motivo |
|---|---|---|
| `app/core/permissions.py:206` | `can_access_quality` | Zero referências, mas é função de autorização. Auth/segurança: escalar. |
| `app/core/permissions.py:151,155,159` | `navigation_for_level`, `consultation_tabs_for_level`, `can_manage_users` | Só usados em `tests/test_permissions.py`. Permissões: escalar. |
| `mes/contracts/ai.py:86` | `AIProvider` (Protocol) | Zero referências no código. Contrato de interface entre camadas: escalar. |
| `mes/contracts/ai.py:106` | `AIConversationRepository` | Zero referências no código. Contrato entre camadas: escalar. |
| `mes/services/rateio.py:7` | `RateioService` | Só em teste e 1 linha de doc. Regra de negócio (rateio): escalar. |
| `mes/services/operational_reports.py:20` | `OperationalReportService` | Só em teste, e `tests/test_import_compatibility.py` protege o import. NÃO remover. |
| `scripts/*.py` (módulos) | `apontar_corte_concluido_origem`, `nemo-hub`, `reiniciar_ops_teste`, `verificar_groq_oee_real` (zero refs); `sanear_recursos`, `sincronizar_sigmanest`, `run_simulacao_industrial`, `package_web_release`, `import_totvs_production_order`, `homologar_totvs_op_sob_demanda_etapa62`, `preencher_planejado_catalogo_status`, `preparar_desenhos_simulacao`, `run_andon_demo`, `sync_test_users`, `verificar_ia_provedor_real` (só doc) | Entrypoints de linha de comando, rodados à mão. Zero referência de código não prova que não são usados. NÃO MEXER. |
| `app/database/bootstrap_admin.py`, `app/database/seed_dev.py` | módulos | Só doc. Entrypoints operacionais (bootstrap/seed). NÃO MEXER. |
| `web/src/**` (55 exports) | ver lista abaixo | Usados internamente pelo próprio arquivo (1 a 11 ocorrências). Apenas perdem o `export`. Não é código morto. Tipos de contrato de API (`types/api.ts`, `types/management.ts`, `types/andon.ts`) NÃO MEXER. |
| 95 defs Python com decorator ou método | rotas, hooks, overrides | Uso dinâmico por framework. NÃO MEXER. |

Lista completa dos 56 exports TS sem uso externo (nome: arquivo:linha): `OperatorStationOccupant`, `FirstPieceChecklist`, `FirstPieceRecord`, `QualityDrawing`, `QualityInspectedPiece`, `TimeCompositionItem`, `ImpactRankingItem`, `ManagementInsights` (`web/src/types/api.ts`); `resolveSystemState`, `reportedValueText` (SEGURO), `SystemStateKey`, `HumanizeOptions`, `ReportedValue` (`web/src/utils/systemState.ts`); `ManagementTab`, `ManagementSection` (`web/src/config/navigation.ts`); `ReferenceClock` (`web/src/system/ReferenceClock.tsx`); `defaultFilters` (`web/src/filters/FilterContext.tsx`); `AndonPhysicalState`, `AndonOperation`, `AndonActiveOp` (`web/src/types/andon.ts`); `isTechnicalName` (`web/src/utils/format.ts`); `isInView`, `ShownNotification`, `NotificationQueue` (`web/src/utils/andonNotifications.ts`); `MapArea`, `StructureBox`, `MapState`, `MapTile`, `FactoryMapModel`, `TileBox` (`web/src/utils/factoryMap.ts`); `fitFocusUnit` (`web/src/hooks/useFocusFit.ts`); `nextTvRotationRoute`, `TV_ROTATION_SECONDS`, `TV_ROTATION_ROUTES`, `TvRotationRoute` (`web/src/hooks/useTvRotation.ts`); `TableColumn` (`web/src/components/DataTable.tsx`); `RowAction` (`web/src/components/RowActions.tsx`); `RecordFilterOption`, `RecordFilterSelect` (`web/src/components/RecordToolbar.tsx`); `ConfirmDialog` (`web/src/components/ConfirmDialog.tsx`); `OperatorNavItem` (`web/src/layouts/OperatorShell.tsx`); `OperatorAction` (`web/src/components/OperatorActionIcon.tsx`); `OP_ALREADY_POINTED_MESSAGE` (`web/src/pages/operator/stationOccupancy.ts`); `MeasureStatus` (`web/src/pages/operator/QualityInspectionPage.tsx`); `BarDatum` (`web/src/components/BarList.tsx`); `ResourceOperation`, `OrderRow`, `SegmentRow`, `TraceOperation`, `TimelineEvent`, `RankedSeconds`, `FirstPieceHistoryRow`, `FirstPieceAuthorizationRow`, `NestingRow` (`web/src/types/management.ts`); `qualityTemplateErrorMessage` (`web/src/pages/production/QualityTemplatesPage.tsx`); `standardTimeErrorMessage` (`web/src/pages/production/StandardTimePage.tsx`). Todos são NÃO MEXER (só retirar `export` é opcional).

Os 2 avisos do pyflakes (F841):
- `mes/integrations/totvs/on_demand.py:313` `resolved_branch_id`. NÃO MEXER: integração TOTVS. Verificar se a chamada atribuída tem efeito antes de tocar.
- `scripts/validate_ai_workforce.py:27` `orchestrator_ids`. Remover só se a expressão não tiver efeito colateral. Classe: NÃO MEXER até verificar.

### Duplicação (corpo idêntico ou quase idêntico)

| Grupo | Locais | Sugestão |
|---|---|---|
| `_dt` (6 arquivos, corpo idêntico) | `mes/analytics/physical_time.py:300`, `mes/analytics/resource_state.py:95`, `mes/services/audit.py:475`, `mes/services/industrial_analytics.py:1122`, `mes/services/management.py:1175`, `mes/services/traceability.py:8` | Consolidar em um helper compartilhado. Escalar se a mudança cruzar camadas. |
| `_as_dict` (3 arquivos) | `app/database/database.py:182`, `app/database/first_piece_repository.py:35`, `app/database/quality_repository.py:23` | Consolidar. |
| `_normalized` (2) | `mes/domain/first_piece.py:89`, `app/core/quality.py:93` | Consolidar. |
| `_enabled` (2, scripts) | `scripts/verificar_groq_oee_real.py:38`, `scripts/verificar_ia_provedor_real.py:41` | Baixa prioridade. |
| `_validate_exact_name` (2, scripts) | `scripts/reiniciar_ops_teste.py:74`, `scripts/resetar_banco_teste.py:132` | Consolidar em um módulo de guarda de banco de teste. |
| `valid_report_type` (2 classes no mesmo arquivo) | `backend/api/schemas/reports.py:24`, `backend/api/schemas/reports.py:55` | Extrair validador comum. |
| `_sha256` / `source_sha256` (quase igual) | `scripts/backup_banco_teste.py:130`, `scripts/seed_dados_ficticios.py:277` | Baixa prioridade. |
| `cookie` (TS) | `web/src/api/client.ts:23`, `web/src/api/ai.ts:5` | Consolidar em `api/client.ts`. |
| `qualityTemplateErrorMessage` / `standardTimeErrorMessage` (TS) | `web/src/pages/production/QualityTemplatesPage.tsx:40`, `web/src/pages/production/StandardTimePage.tsx:71` | Consolidar em um helper de mensagem de erro. |

Além disso, 37 nomes Python de nível superior aparecem em mais de um arquivo com corpos diferentes. São candidatos a duplicação parcial, não verificados um a um.

## Contagens

- SEGURO REMOVER: 4 definições sem nenhuma referência (`reportedValueText`, `is_operator_level`, `resource_path`, `ensure_data_dir`) + 4 itens TS6133 = 8 itens.
- Escalados (auth/contrato/regra): `can_access_quality`, `AIProvider`, `AIConversationRepository`, `RateioService`, além de `navigation_for_level`, `consultation_tabs_for_level` e `can_manage_users`, que só têm teste.
- PROVÁVEL MORTO: 2 (`summarize_physical_states`, `PendingCorporateIntegration`).
- NÃO MEXER / ESCALAR: restante (permissões, contratos, scripts, rotas, decorators, exports internos, integrações, 2 avisos F841).
- Duplicação: 9 grupos (7 Python, 2 TS).
- Não rodado: vulture.

## Limitações

- Vulture não estava instalado; a varredura Python foi feita com AST própria. Nomes muito comuns (`run`, `get`, `main`) não são acusados, o que dá falso negativo, não falso positivo.
- A grep de referências é por palavra: nome igual em outro contexto conta como referência (conservador).
- `.env` não foi lido (não é necessário e contém segredos).
- Pasta de quarentena não localizada no repo, então não foi considerada.
