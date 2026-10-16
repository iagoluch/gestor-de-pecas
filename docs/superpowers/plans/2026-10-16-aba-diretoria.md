# Aba "Diretoria" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar à diretoria (e ao admin) uma aba com Painel + Ficha por setor/recurso e custo por hora (recurso e pessoa), com respostas prontas em português e valores em R$ restritos a esses dois níveis.

**Architecture:** Um serviço novo (`DirectorSummaryService`) só **consome** `ManagementService.get_overview`, `IndustrialAnalyticsService.downtimes` e as participações de operador já existentes; a única regra nova é a fórmula do custo, isolada numa função pura. Os R$/h ficam em **duas tabelas novas**, lidas apenas por rotas novas `/api/v1/diretoria/*` protegidas por uma dependência `require_diretoria_user`. O frontend ganha uma seção "Diretoria" no menu, com guarda de rota espelhando o backend (mesmo padrão do "Tempo padrão").

**Tech Stack:** Python/FastAPI, PostgreSQL (migrations numeradas), React/TypeScript (`useApiQuery`), unittest/pytest + vitest.

**Spec:** `docs/superpowers/specs/2026-10-16-aba-diretoria-design.md` (mockup: `.superpowers/brainstorm/4931-1792150485/content/aba-diretoria.html`, números inventados).

## Global Constraints

- Níveis com acesso (ver e editar R$): exatamente `("admin", "diretoria")`. Nenhum outro nível recebe R$ em nenhuma resposta, log ou relatório.
- R$/h em **tabelas separadas** (`custo_hora_recurso`, `custo_hora_operador`); nunca coluna em `recursos`/`operadores_apontamento`/tabelas lidas por rotas existentes.
- Só **parada não planejada** gera custo (mesmo critério do OEE: `ManufacturingRules.stop_affects_oee` / `StopClassification`); pausa automática (almoço/café), sem demanda e fora de turno **não** geram custo e aparecem como linhas separadas.
- Fórmula: `horas_paradas × (R$/h do recurso + Σ R$/h das pessoas alocadas ao recurso durante a parada)`. Custo faltando conta R$ 0 **e** a resposta marca `custo_completo=false` com `custos_faltando=N`; a tela mostra "faltam custos de N recursos/pessoas — o valor real é maior".
- "Pessoa" = operador do chão (`operadores_apontamento`, crachá), não conta de login.
- Não recalcular OEE/disponibilidade/paradas: consumir os serviços existentes. Números da aba = números da Visão Geral/OEE no mesmo período.
- Períodos: `hoje` (dia de turno), `semana` (corrente até agora), `mes` (corrente até agora), alinhados ao que a Visão Geral aceita.
- Valor/hora sem histórico na v1 (usa o valor atual). Valor ≤ 0 ou não numérico → 422.
- Migration: **testar primeiro no banco de teste; não aplicar no REAL sem ok do Iago.** Nenhum commit sem pedido do usuário; o working tree tem trabalho não commitado da "fila manual" (migration 62) que não pode ser sobrescrito nem commitado junto.
- Mudança visual: imagem da tela como prova + autocrítica "Eu fiz certo? Por quê?" antes de commitar. Sem botão flutuante; linguagem sem jargão.

## Review Focus

- Período sem nenhuma parada/produção: texto da ficha e cards devem dizer "sem paradas no período" / 0, sem divisão por zero nem "NaN h".
- Parada ainda em andamento (`em_andamento=True`, `fim=filters.fim`): conta até o fim do período, uma única vez, sem duplicar.
- Pessoa alocada a dois recursos ao mesmo tempo (ou dois operadores no mesmo recurso): a soma usa as participações existentes, sem rateio novo e sem contar a mesma participação duas vezes na mesma parada.
- Nenhum custo cadastrado: ranking continua ordenado por horas, R$ = 0, `custo_completo=false` e o aviso aparece (nunca "R$ 0" sem aviso).
- Usuário `gestor`/`lider`/`pcp`/sem sessão chama qualquer rota nova → 403/401 e nenhuma outra rota existente passa a devolver campo de custo.

---

### Task 1: Migration e repositório de custo por hora

**Files:**
- Modify: `app/database/migrations.py` (novo bloco `CUSTO_HORA_DESCRIPTION`/`CUSTO_HORA_STATEMENTS` e entrada no dicionário `MIGRATIONS`, depois da 62)
- Modify: `app/database/schema.py` (`SCHEMA_VERSION`)
- Create: `app/database/cost_rate_repository.py`
- Modify: `app/database/database.py` (expor os métodos abaixo, no padrão de `manual_queue_repository` já em uso)
- Modify: `scripts/resetar_banco_teste.py` (incluir as tabelas novas no reset, como a fila manual fez)
- Test: `tests/test_cost_rate_postgres.py` (mesmo estilo de `tests/test_standard_time_postgres.py`)

**Interfaces:**
- Consumes: padrão de migration/`MIGRATIONS` existente; `operadores_apontamento(id)`.
- Produces (em `Database`): `listar_custos_hora_recurso() -> list[dict]` (`recurso`, `valor_hora`, `atualizado_em`, `atualizado_por`), `salvar_custo_hora_recurso(recurso: str, valor_hora: Decimal, usuario: str) -> None` (upsert; chave = `UPPER(recurso)`), `listar_custos_hora_operador() -> list[dict]` (`operador_id`, `valor_hora`, …), `salvar_custo_hora_operador(operador_id: int, valor_hora: Decimal, usuario: str) -> None`.

- [ ] **Step 1: Número da migration.** Conferir `SCHEMA_VERSION` atual no working tree. Hoje é 62 (fila manual, não commitada) → esta migration é **63**. Se a fila manual ainda não estiver aplicada/commitada, avisar o usuário da ordem antes de seguir; nunca reutilizar o 62.
- [ ] **Step 2: Teste falhando** em `tests/test_cost_rate_postgres.py`: (a) migrar banco descartável até 63 e conferir que as duas tabelas existem; (b) `salvar_custo_hora_recurso("laser1", 250)` seguido de `salvar_custo_hora_recurso("LASER1", 300)` deixa **uma** linha com 300; (c) `salvar_custo_hora_operador` com `operador_id` inexistente levanta erro de FK; (d) `CHECK (valor_hora > 0)` rejeita 0 e negativo.
- [ ] **Step 3:** Rodar `pytest tests/test_cost_rate_postgres.py -v` — esperado: FAIL (tabelas/métodos ausentes).
- [ ] **Step 4: Implementar** as duas tabelas (`custo_hora_recurso(recurso_chave TEXT PK, recurso TEXT, valor_hora NUMERIC(12,2) CHECK > 0, atualizado_em, atualizado_por)`; `custo_hora_operador(operador_id BIGINT PK REFERENCES operadores_apontamento ON DELETE CASCADE, valor_hora …, atualizado_em, atualizado_por)`), o repositório e a exposição em `Database`. Subir `SCHEMA_VERSION` e registrar em `MIGRATIONS`.
- [ ] **Step 5:** Rodar o teste — esperado: PASS. Rodar também `pytest tests/ -k "migration or schema" -q` (guarda `validate_migration_catalog`).
- [ ] **Step 6:** Aplicar a migration **só no banco de teste** (conforme o fluxo do projeto) e conferir a versão. Não tocar no REAL.
- [ ] **Step 7: Commit** (somente se o usuário pedir): `git add app/database/migrations.py app/database/schema.py app/database/cost_rate_repository.py app/database/database.py scripts/resetar_banco_teste.py tests/test_cost_rate_postgres.py` — separar dos arquivos da fila manual (`git add -p` onde `database.py`/`migrations.py`/`schema.py` se misturarem).

### Task 2: Fórmula do custo (função pura)

**Files:**
- Create: `mes/domain/director_cost.py`
- Test: `tests/test_director_cost.py`

**Interfaces:**
- Consumes: nada de banco; recebe estruturas simples.
- Produces:
  - `@dataclass(frozen=True) CostResult`: `horas: float`, `custo: Decimal`, `completo: bool`, `recursos_sem_custo: tuple[str, ...]`, `pessoas_sem_custo: tuple[str, ...]`
  - `stop_cost(stops: Sequence[StopSlice], rates: CostRates) -> CostResult` onde `StopSlice(recurso: str, inicio: datetime, fim: datetime, pessoas: tuple[str, ...])` (pessoas = crachás alocados durante o trecho; o chamador já fatiou a parada pelas participações) e `CostRates(recurso: Mapping[str, Decimal], pessoa: Mapping[str, Decimal])` (chaves em maiúsculas).
  - `work_cost(...)` com a mesma assinatura para as horas trabalhadas.

- [ ] **Step 1: Testes falhando** (nomes e asserts): `test_parada_de_2h_recurso_100_duas_pessoas_50_custa_400` (2h × (100+50+50) = 400, `completo=True`); `test_recurso_sem_custo_marca_incompleto_e_lista_o_recurso`; `test_pessoa_sem_custo_marca_incompleto_e_lista_a_pessoa`; `test_sem_paradas_devolve_zero_horas_zero_reais_completo`; `test_mesma_pessoa_duas_vezes_no_mesmo_trecho_conta_uma_vez`.
- [ ] **Step 2:** `pytest tests/test_director_cost.py -v` — esperado: FAIL (módulo inexistente).
- [ ] **Step 3: Implementar** `stop_cost`/`work_cost` em `mes/domain/director_cost.py`; usar `Decimal` e arredondar a 2 casas só na saída.
- [ ] **Step 4:** Rodar — esperado: PASS (5 testes).

### Task 3: Permissão `diretoria`/`admin`

**Files:**
- Modify: `app/core/permissions.py` (constante e `can_view_director_tab`)
- Modify: `backend/api/dependencies/auth.py` (`require_diretoria_user`)
- Modify: `web/src/config/navigation.ts` (espelho da constante + seção "Diretoria")
- Modify: `web/src/App.tsx` (guarda `RequireDiretoriaAccess` e rota `/diretoria`)
- Test: `tests/test_director_permissions.py`, `web/src/test/director-access.test.tsx`

**Interfaces:**
- Produces: `DIRECTOR_LEVELS = ("admin", "diretoria")`; `can_view_director_tab(level) -> bool`; dependência FastAPI `require_diretoria_user(user: SessionUser = Depends(get_current_user)) -> SessionUser` (403 `AppError` para os demais); no front, `DIRECTOR_LEVELS` em `navigation.ts` e a rota `/diretoria`.

- [ ] **Step 1: Testes falhando.** Backend: `can_view_director_tab` é True só para `admin` e `diretoria` e False para todos os outros itens de `USER_LEVELS` (iterar a lista). Frontend: usuário `gestor` não vê o item "Diretoria" no menu e `/diretoria` redireciona; `diretoria` vê.
- [ ] **Step 2:** `pytest tests/test_director_permissions.py -v` e `npx vitest run src/test/director-access.test.tsx` (em `web/`) — esperado: FAIL.
- [ ] **Step 3: Implementar** seguindo o precedente de `STANDARD_TIME_LEVELS`/`require_tempo_padrao_user`/`RequireStandardTimeAccess`.
- [ ] **Step 4:** Rodar os dois — esperado: PASS.

### Task 4: Serviço de resumo (Painel + Ficha + Custos)

**Files:**
- Create: `mes/services/director_summary.py`
- Test: `tests/test_director_summary.py` (usa `tests/fakes.FakeDatabase` e `tests/test_industrial_analytics._ManagementRepo`, como `test_standard_time.py`)

**Interfaces:**
- Consumes: Task 1 (`listar_custos_hora_*`, `salvar_custo_hora_*`, `listar_participacoes_operador_periodo`, `listar_operadores_apontamento`); Task 2 (`stop_cost`, `work_cost`, `CostRates`, `StopSlice`); `ManagementService.get_overview(filters)` (chaves `production`, `hours`, `kpis`, `resource_kpis`, `sector_kpis`, `sectors`); `IndustrialAnalyticsService.downtimes(filters)` (`items[*]`: `setor`, `recurso`, `inicio`, `fim`, `segundos`, `motivo`, `programada`, `automatica`, `em_andamento`; `by_reason`).
- Produces:
  - `resolve_period(name: Literal["hoje","semana","mes"], now: datetime) -> tuple[datetime, datetime]` (alinhar com o período da Visão Geral; conferir como ela resolve "dia de turno").
  - `DirectorSummaryService.panel(period: str, now: datetime) -> dict` → `{periodo, cards{produzido, horas_paradas, custo_parada, eficiencia_oee}, onde_perdemos[3]{setor, horas_paradas, custo, motivo_principal}, melhor_setor{nome, oee}, pior_setor{nome, oee}, custo_completo, custos_faltando}`.
  - `DirectorSummaryService.sheet(period: str, setor: str|None, recurso: str|None, now: datetime) -> dict` → `{texto, trabalhou_h, disponivel_h, produzido, custo_trabalho, parado_h, custo_parada, motivo_principal, paradas_por_motivo[{motivo, horas}], sem_demanda_h, fora_turno_h, pessoas[{nome, horas, custo}], custo_completo, custos_faltando}`.
  - `DirectorSummaryService.costs() -> dict` → `{recursos[{recurso, setor, valor_hora|null}], pessoas[{operador_id, nome, cracha, valor_hora|null}]}`; `set_resource_rate(recurso, valor, usuario)` e `set_operator_rate(operador_id, valor, usuario)` (valida `> 0`, levanta `AppError("COST_RATE_INVALID", ..., 422)`).

- [ ] **Step 1: Testes falhando** com dados determinísticos: (a) cards do painel batem com `get_overview` do mesmo filtro (horas paradas e OEE idênticos — nenhum recálculo); (b) `onde_perdemos` ordena por horas paradas **não planejadas** decrescente, máximo 3, e ignora `automatica`/`programada`; (c) `texto` da ficha para LASER1 = frase exata do spec ("O LASER1 (Corte) trabalhou 31 h de 40 h … Ficou parado 9 h, o que custou R$ 2.250. Principal motivo: falta de material (5 h)."); (d) sem custos cadastrados → `custo_completo=False`, `custos_faltando>0`, texto inclui o aviso; (e) período vazio → `texto` "sem paradas no período", sem exceção; (f) `set_resource_rate(..., 0)` e valor negativo → `AppError` 422.
- [ ] **Step 2:** `pytest tests/test_director_summary.py -v` — esperado: FAIL.
- [ ] **Step 3: Implementar** `resolve_period`, `panel`, `sheet`, `costs` e os dois setters em `mes/services/director_summary.py`. Para cada parada não planejada (`stop_affects_oee`) fatiar pelo `listar_participacoes_operador_periodo` do recurso e montar `StopSlice`; "trabalhou/disponível" vêm de `hours`/`resource_kpis` do `get_overview`, **sem** prometer trabalhado + parado = turno; `sem_demanda_h` e `fora_turno_h` vêm dos baldes do overview.
- [ ] **Step 4:** Rodar — esperado: PASS.

### Task 5: Rotas `/api/v1/diretoria` e testes de vazamento

**Files:**
- Create: `backend/api/routers/director.py`, `backend/api/schemas/director.py`
- Modify: `backend/api/main.py` (registrar o router, ao lado dos demais)
- Test: `tests/test_director_api.py`

**Interfaces:**
- Consumes: Task 3 (`require_diretoria_user`, `require_csrf`), Task 4 (`DirectorSummaryService`).
- Produces: `GET /api/v1/diretoria/painel?periodo=hoje|semana|mes`; `GET /api/v1/diretoria/ficha?periodo=&setor=&recurso=`; `GET /api/v1/diretoria/custos`; `PUT /api/v1/diretoria/custos/recurso/{recurso}` e `PUT /api/v1/diretoria/custos/pessoa/{operador_id}` (corpo `{valor_hora: number}`, exigem CSRF). Todas só para `admin`/`diretoria`.

- [ ] **Step 1: Testes falhando** (TestClient, `get_current_user`/`require_csrf` sobrescritos como em `test_standard_time.py`): `diretoria` e `admin` recebem 200 e campos de R$ em painel/ficha/custos; para **cada** outro nível de `USER_LEVELS` todas as 5 rotas dão 403; sem sessão 401; PUT sem CSRF falha; PUT com valor 0 → 422. **Vazamento:** chamar as rotas existentes de gestão (visão geral, recursos, operadores, relatórios, tempo padrão) como `diretoria` e como `gestor` e afirmar que nenhuma resposta contém as chaves `valor_hora`/`custo`/`custo_parada`.
- [ ] **Step 2:** `pytest tests/test_director_api.py -v` — esperado: FAIL.
- [ ] **Step 3: Implementar** o router no padrão de `backend/api/routers/management.py` (`APIRouter(prefix="/diretoria", dependencies=[Depends(require_diretoria_user)])`), schemas Pydantic de resposta e registrar em `backend/api/main.py`. Erro de regra sai como `AppError` (409/422 estruturado), nunca texto solto.
- [ ] **Step 4:** Rodar — esperado: PASS. Rodar também `pytest tests/test_standard_time.py -q` (nenhuma rota existente quebrou).

### Task 6: Frontend — aba Diretoria

**Files:**
- Create: `web/src/pages/director/DirectorPage.tsx` (Painel + Ficha + Custos), `web/src/pages/director/DirectorPanel.tsx`, `DirectorSheet.tsx`, `DirectorCosts.tsx`
- Modify: `web/src/api/client.ts` (funções `getDirectorPanel`, `getDirectorSheet`, `getDirectorCosts`, `putResourceRate`, `putOperatorRate`, com CSRF no padrão existente), `web/src/types/` (tipos espelhando os schemas da Task 5), `web/src/App.tsx` (rota já criada na Task 3 passa a renderizar `DirectorPage`), `web/src/styles/global.css` (usar tokens existentes)
- Test: `web/src/test/director-page.test.tsx`

**Interfaces:**
- Consumes: rotas da Task 5; `useApiQuery`.
- Produces: tela com seletor Hoje/Semana/Mês; Painel (4 cards, top-3 "Onde mais perdemos" clicável que abre a Ficha já filtrada no setor, destaques melhor/pior); Ficha (filtros Setor/Recurso/Período, parágrafo `texto` em destaque **antes** de qualquer detalhe, paradas por motivo, "quem operou", linhas "sem demanda"/"fora do turno" sem R$); Custos (lista de recursos e pessoas com campo R$/h editável; salvar por linha; pt-BR com vírgula).

- [ ] **Step 1: Testes falhando** (vitest, `client` mockado): painel mostra "R$" e o aviso "faltam custos de 3 recursos/pessoas — o valor real é maior" quando `custo_completo=false`; clicar no setor do ranking abre a Ficha com aquele setor selecionado; a Ficha mostra o `texto` recebido antes da lista de motivos; editar R$/h "12,50" chama `putResourceRate("LASER1", 12.5)`; erro 422 aparece como mensagem legível; período vazio mostra "sem paradas no período".
- [ ] **Step 2:** `npx vitest run src/test/director-page.test.tsx` (em `web/`) — esperado: FAIL.
- [ ] **Step 3: Implementar** as páginas e as chamadas em `client.ts`, seguindo o design system atual (mockup é guia de conteúdo, não de pixel). Sem botão flutuante; textos sem jargão.
- [ ] **Step 4:** Rodar o teste + `npx tsc --noEmit` + `npx vitest run src/test/director-access.test.tsx` — esperado: PASS.

### Task 7: Verificação final (R3)

**Files:** nenhum novo; evidências em `dev_reports/` (fora do Git, repo público).

- [ ] **Step 1:** `pytest tests/test_cost_rate_postgres.py tests/test_director_cost.py tests/test_director_permissions.py tests/test_director_summary.py tests/test_director_api.py -q` e `npx vitest run` dos arquivos `director-*` — tudo verde. Não rodar a suíte inteira (política de economia).
- [ ] **Step 2: Prova visual.** Subir API+web em teste (preview), logar como `ezequiel` (nível `diretoria`), cadastrar alguns R$/h e capturar Painel, Ficha e Custos; logar como `gestor` e confirmar que o item "Diretoria" não existe e `/diretoria` redireciona. Escrever a autocrítica "Eu fiz certo? Por quê?" apontando o que da tela pode não responder à pergunta da diretoria.
- [ ] **Step 3: Conferência de números.** No mesmo período, comparar OEE e horas paradas do Painel com a Visão Geral; divergência = bug (anti-meta do spec).
- [ ] **Step 4: Revisão independente.** `qa-test-engineer` (tentar quebrar: parada em andamento, pessoa em dois recursos, nada cadastrado, período vazio) e `technical-reviewer` (vazamento de R$, migration, fórmula contra o OEE). Corrigir achados.
- [ ] **Step 5:** Reportar ao usuário: migration só no teste (REAL aguardando ok), nada commitado, pendências do spec "Aberto" (histórico de valor/hora) mantidas.
