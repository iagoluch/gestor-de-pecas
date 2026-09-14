# Consolidação Web-only e correção arquitetural — 24/08/2026

## Resultado

A interface operacional oficial do Gestor de Peças é exclusivamente Web:

```text
React / TypeScript -> FastAPI -> services/contracts -> domain/analytics -> PostgreSQL
```

Não existe entrypoint, dependência ou pacote funcional PySide6/Qt. O backend é
a autoridade das transições e quantidades; o React apenas apresenta o estado e
envia ações.

## Alterações realizadas

### Arquivos criados

- `mes/domain/operator_state_machine.py`: máquina de estados canônica;
- `tests/test_operator_state_machine.py`: testes focados nas transições e nos
  estados físicos;
- `docs/WEB_ONLY_CONSOLIDATION_20260824.md`: este relatório.

### Arquivos funcionais modificados

- persistência e schema: `app/database/database.py`,
  `app/database/migrations.py`, `app/database/schema.py`;
- domínio: `mes/domain/__init__.py`, `mes/domain/industrial.py`,
  `mes/domain/manufacturing_rules.py`;
- serviços: `mes/services/operator_flow.py`, `mes/services/production.py`,
  `mes/services/frontend_facade.py`, `mes/services/management.py`,
  `mes/services/industrial_analytics.py`, `mes/services/operational_reports.py`,
  `mes/services/audit.py`, `mes/services/resource_state.py` e
  `mes/services/shift_boundary.py`;
- contratos/API: `mes/contracts/__init__.py`, `mes/contracts/frontend.py`,
  `mes/contracts/management.py`, `backend/api/schemas/operator.py`;
- frontend: `web/src/pages/operator/WorkbenchPage.tsx` e
  `web/src/test/operator.test.tsx`;
- testes: `tests/fakes.py`, `tests/test_database_professionalization.py`,
  `tests/test_import_compatibility.py`, `tests/test_production_service.py` e
  `tests/test_web_api.py`;
- empacotamento: `scripts/package_web_release.py`;
- textos auxiliares sem regra nova: `app/core/normalization.py`,
  `app/core/paths.py` e `tools/extract_operator_mockup_assets.py`.

### Arquivos de arquitetura e documentação modificados

- `README.md`, `.env.example`, `requirements.txt` e `AGENTS.md`;
- `docs/WEB_ARCHITECTURE.md`, `docs/WEB_TARGET_ARCHITECTURE.md`,
  `docs/WEB_DEPLOYMENT.md`, `docs/WEB_MIGRATION_STATUS.md`,
  `docs/WEB_FINAL_VALIDATION.md`, `docs/OPERATOR_SCREEN_FLOW.md`,
  `docs/MANAGEMENT_DATA_FOUNDATION.md`,
  `docs/INTEGRACAO_CORPORATIVA_TOTVS_PENDENTE.md` e
  `docs/REFERENCIA_MES_MANAGEMENT_VIEW_20260819.md`;
- documentos datados anteriores receberam identificação explícita de registro
  histórico: `BACKEND_CONSOLIDADO_V11_FRONTEND_READY.md`,
  `HOMOLOGACAO_EXTREMA.md`, `HOTFIX_V11_LOGIN_20260819.md`,
  `IMPLEMENTATION_STATUS_MANAGEMENT_WEB.md`,
  `PROGRESSO_LOGICA_INDUSTRIAL_20260819.md`,
  `REFATORACAO_UI_OPERACIONAL_V12_20260819.md`, `VALIDATION_REPORT.md` e
  `WEB_MIGRATION_BASELINE.md`.

`web/dist/` foi regenerado pelo build de produção.

## Desktop removido

Foram removidos:

- `app/ui/` completo: componentes, widgets, workers, teclado, dashboards,
  relatórios, histórico, bancada do operador, design system e todas as seções
  da janela principal;
- `app/main_window.py` e `app/launcher.py`;
- módulos de runtime exclusivamente gráfico:
  `app/core/config.py`, `app/core/matplotlib_backend.py`,
  `app/core/runtime.py`, `app/core/runtime_mode.py` e `app/core/styles.py`;
- entrypoints `gestordepeca.py` e `gestordepeca_teste.py`;
- `scripts/base_teste.py`;
- ferramentas de captura/comparação Qt:
  `tools/capture_operator_screen.py`,
  `tools/capture_test_entrypoint_catalog.py` e
  `tools/operator_visual_compare.py`;
- testes exclusivos da interface removida:
  `tests/test_apontamento_ui.py`, `tests/test_core_config.py`,
  `tests/test_keyboard.py`, `tests/test_official_design.py`,
  `tests/test_operator_screen_flow.py`, `tests/test_qt_migration.py`,
  `tests/test_runtime_cleanup.py` e `tests/test_runtime_mode.py`;
- o catálogo `docs/capturas_entrypoint_teste_2026-08-20/`, com 148 arquivos
  gerados exclusivamente pelo entrypoint desktop;
- dependências `PySide6` e `matplotlib` de `requirements.txt`.

Os mockups e assets oficiais que continuam servindo de referência ou são
consumidos pela Web foram preservados. Os itens removidos possuem backups ZIP
fora do workspace.

## Máquina de estados canônica

A definição única está em `mes/domain/operator_state_machine.py`:

```text
Fila        -> Produção | Parada | Setup | Retrabalho
Produção    -> Parada | Setup | Retrabalho | Finalizado
Parada      -> Produção | Retrabalho | Finalizado
Setup       -> Produção | Retrabalho | Finalizado
Retrabalho  -> Parada | Setup | Finalizado
Finalizado  -> terminal
```

Compatibilidades preservadas:

- Parada, Setup e Retrabalho continuam podendo finalizar;
- `Início` permanece aceito para clientes anteriores e, quando usado em
  Parada/Setup, respeita o contexto de retorno;
- `Retomar` e `Retornar` são ações Web explícitas;
- parada física sem OP continua sendo um caso de uso próprio, sem inventar uma
  OP ou operação.

`estado_retorno` preserva `producao` ou `retrabalho` ao entrar em Parada/Setup.
Assim, Retrabalho -> Parada -> Retomar e Retrabalho -> Setup -> Retornar
retornam a Retrabalho.

## Caminhos legados eliminados

Foram removidos de `ProductionService` e `Database` os caminhos paralelos
`iniciar_apontamento_operacional()` e `finalizar_apontamento_operacional()`,
além dos wrappers de fila/finalização que os expunham. Esse fluxo antigo podia
finalizar atribuindo toda a quantidade planejada como boa e refugo zero.

O apontamento agora passa por `OperatorFlowService`, pela máquina de estados do
domínio e por `Database.transicionar_apontamento_operador()`. A finalização
exige quantidades explícitas e mantém peças boas, refugo e retrabalho separados.

Não existe rota HTTP `PUT`, `PATCH` ou `DELETE` para reescrever/apagar eventos
produtivos. A correção administrativa de cadastro/planejamento de OP permanece
interna e auditada; ela não edita eventos históricos de execução.

## Correções encontradas

1. A migration v12 admitia `fila`, mas a validação de persistência não. A
   enumeração física agora deriva de `EventCategory`, incluindo:
   `fila`, `producao`, `parada`, `setup`, `retrabalho`, `atividade_sem_op`,
   `fora_turno` e `desconhecido`.
2. Transições estavam duplicadas no serviço e na persistência. Ambos agora
   consomem a mesma definição de domínio.
3. Parada/Setup perdiam a origem Retrabalho. O contexto passou a ser persistido
   no apontamento e no evento.
4. Uma entrada direta em Parada, Setup ou Retrabalho podia ficar sem
   `data_inicio`, escapando da reconciliação do estado físico. Toda entrada
   ativa agora inicializa a sessão.
5. O caminho canônico não alimentava a localização corrente usada pelas
   consultas da Serra. O início grava movimentação para o recurso e a conclusão
   total grava movimentação da quantidade boa para o destino, na mesma
   transação e sem inferir produção.
6. O empacotador podia incluir dados locais, saídas, cookies Qlik e uma pasta
   acidental `%SystemDrive%`. Esses alvos agora são excluídos do ZIP Web.

OEE, FTT, rateio, analytics, Corte/Nesting, Destaque, calendário, fim de turno,
auditoria, rastreabilidade e SSE não tiveram sua regra funcional alterada.

## Banco

Foi criada a migration incremental `13`, sem reescrever migrations anteriores.
Ela:

- adiciona `estado_retorno` anulável a `apontamentos_operacionais` e
  `eventos_apontamento_operador`;
- limita o campo a `producao` ou `retrabalho`;
- mantém `estado_retorno = NULL` em apontamentos e eventos anteriores;
- não altera estados, horários nem quantidades históricas.

A migration foi exercitada em schemas temporários dentro de
`gestor_pecas_test`. Nenhum schema/tabela/dado operacional foi limpo ou
alterado durante esta execução.

## Testes

Resultado final:

```text
executados: 200 testes (187 Python + 13 Web)
aprovados:  200
falharam:   0
ignorados:  0
```

Verificações adicionais:

- 26 testes PostgreSQL executados em schemas isolados de `gestor_pecas_test`;
- `python -m compileall`: aprovado;
- `npm run build`: aprovado, 119 módulos transformados;
- pacote Web: 602 arquivos, todos os nomes marcados como UTF-8 e nenhuma
  entrada proibida detectada;
- buscas por imports/requisitos/entrypoints PySide6, `QApplication`,
  `QMainWindow` e `QWidget`: nenhuma ocorrência funcional;
- as menções restantes à interface removida estão somente em documentos
  datados e explicitamente classificados como históricos.

## Pendências não alteradas

- definição do contrato corporativo Protheus/TOTVS pela TI;
- validação manual no navegador com usuário autorizado, leitor de crachá e
  operação real controlada;
- validação de rede/reverse proxy e observação SSE em implantação;
- aplicação da migration 13 no ambiente alvo durante o procedimento controlado
  de implantação.

Telegram/mensageria, Checklist, Andon, IA, Manutenção, CEP, Ferramental,
documentos por OP, PLC/OPC/Modbus e sequenciamento avançado permanecem fora do
escopo desta consolidação.
