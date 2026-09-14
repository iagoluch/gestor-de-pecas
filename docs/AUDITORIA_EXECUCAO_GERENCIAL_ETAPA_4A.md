# Etapa 4A — Auditoria execução → dados gerenciais

**Estado:** CONCLUÍDA · 31/08/2026
**Escopo:** provar que tudo que nasce na Tela do Operador alimenta uma única
fonte confiável para histórico, estado do recurso, tempos, quantidades e
indicadores. A fábrica fictícia (Etapa 4B) não foi iniciada.

## 1. Fluxo auditado

```text
Tela do Operador
  ↓ POST /api/v1/operator/actions        (backend/api/routers/operator.py)
OperatorFlowService.executar             (mes/services/operator_flow.py)
  ↓ resolve_operator_action + validate_transition
máquina de estados                       (mes/domain/operator_state_machine.py)
  ↓ Database.transicionar_apontamento_operador   — uma transação
apontamentos_operacionais                (estado e acumulado da etapa)
eventos_apontamento_operador             (um evento por transição)
eventos_estado_recurso                   (reconciliação do estado físico)
eventos_quantidade_producao              (boa / refugo / retrabalho)
historico                                (leitura humana + movimentação)
  ↓
ManagementService.get_overview           (mes/services/management.py)
  ├─ consolidate_physical_time           (mes/analytics/physical_time.py)
  ├─ build_operator_timeline             (mes/analytics/timeline.py)
  └─ calculate_oee                       (mes/analytics/oee.py)
  ↓
FrontendBackendFacade                    (mes/services/frontend_facade.py)
  ├─ inicio()               → Dashboard / KPIs
  ├─ consulta_operacional() → estado atual dos recursos
  └─ andon()                → AndonService.build_snapshot
```

## 2. Fonte canônica por informação

| Informação | Fonte canônica | Fallback explícito |
|---|---|---|
| Estado físico do recurso | `eventos_estado_recurso` | `categoria = "desconhecido"`, nunca inferido |
| Quantidade boa/refugo/retrabalho | `eventos_quantidade_producao` | colunas de `apontamentos_operacionais`, marcado em `production.source` |
| Execução da OP (estado, acumulado) | `apontamentos_operacionais` | — |
| Histórico de transições | `eventos_apontamento_operador` | — |
| Motivo de parada | `catalogo_status_recursos` via `codigo_status_recurso` | — |
| Tempo físico | `sessoes_recurso` / estados + `consolidate_physical_time` | segmentos do apontamento |
| Corte / nesting | `apontamentos_corte` + `catalogo_sigmanest_planos_corte` | — |
| OEE / Disponibilidade / Performance / FTT | `mes/analytics/oee.py::calculate_oee` | — |
| Leitura humana | `historico` | — |

`ManagementService` expõe qual fonte usou (`production.source`) e a consulta
operacional marca `fonte: "eventos_estado_recurso"`. Ausência não vira zero.

## 3. Não há cálculo duplicado entre telas

Verificado e travado por teste:

- **Andon não recalcula nada.** `AndonService.build_snapshot` recebe
  `consulta_operacional` e `inicio` prontos e apenas reagrupa por setor. Não
  importa `calculate_oee`, `consolidate_physical_time` nem
  `build_operator_timeline`;
- **Dashboard e Andon partem do mesmo `get_overview`**, com cache por filtro;
- **O frontend não calcula indicador industrial.** As páginas apenas formatam.

## 4. Divergência encontrada — relógio da sessão PostgreSQL

### Sintoma

Um nesting iniciado há segundos aparecia com **03:00:22** de tempo realizado no
detalhamento por nesting da tela de Corte.

### Causa

```text
Aplicação (agora_db)     : datetime.now()      → 09:31:30  (local, naive)
Sessão PostgreSQL        : TimeZone = UTC      → 12:31:30
```

Toda duração calculada **em SQL** contra `CURRENT_TIMESTAMP` ficava deslocada
pelo offset (3 h) enquanto a execução estava aberta. Com `data_fim` preenchido a
conta usa duas colunas da aplicação e continuava correta — por isso o erro só
aparecia em execução em andamento.

`CutService._group_rows` recalcula o total do card em Python e mascarava o
problema no card; o **detalhamento por nesting** preservava o valor cru do SQL.

### Impacto medido

| Caminho | Antes | Depois |
|---|---:|---:|
| `listar_fila_corte` (card, recalculado em Python) | 0,1 s | 0,1 s |
| `listar_tempos_nesting_corte` (SQL) | **10.800,2 s** | 0,2 s |
| Python (operador / management / Andon) | 0,2 s | 0,2 s |

`listar_tempos_nesting_corte` alimenta `ManagementService.get_overview` →
`cutting_real_seconds`. Cada nesting aberto inflava **3 h de tempo produtivo**
nos indicadores. Também afetava `listar_apontamentos_corte`,
`listar_nestings_corte_por_op` e a janela de `listar_fatos_operacionais_periodo`.

### Correção mínima aplicada

`PostgresPoolManager` passou a alinhar o fuso da sessão ao fuso em que a
aplicação grava, via `configure` do pool:

```sql
SELECT set_config('TimeZone', 'America/Sao_Paulo', false)
```

Configurável por `GESTOR_DB_TIMEZONE`; o padrão está em
`app/database/config.py::DEFAULT_SESSION_TIMEZONE`.

Isso corrige as sete consultas de uma vez, **sem alterar nenhuma regra de
apontamento, nenhuma migration e nenhum dado gravado**. Não é escolha de uma
política nova: 100% das escritas da aplicação já eram hora local; o banco é que
não acompanhava.

> A migração completa para UTC continua sendo decisão separada e maior, pois
> exigiria reinterpretar todo o histórico já gravado.

## 5. Divergência menor registrada, não corrigida

`web/src/pages/ManagementOverviewPage.tsx` mantém um `hours()` local que
converte segundos com formato próprio (`1,5 h`), enquanto o restante do produto
usa `formatHours` de `utils/format.ts` (`1h 30m`). É divergência de
**apresentação**, não de cálculo. Consolidar muda rótulo visível e depende de
decisão de UI. Um teste impede que novas conversões locais apareçam.

## 6. Cobertura automatizada

`tests/test_execution_to_management_consistency.py`:

1. ciclo Início → Setup → Retornar → Parada → Retomar → Retrabalho → parcial →
   Finalizado, conferindo estado, motivo, comentário, crachá, recurso do
   roteiro e recurso apontado;
2. quantidades boa/refugo separadas em `eventos_quantidade_producao`;
3. estado físico registrado em `eventos_estado_recurso`;
4. histórico legível em `historico`;
5. leitura gerencial batendo com a execução, declarando a fonte;
6. Andon projetando a mesma categoria de estado, sem recalcular;
7. OP de origem TOTVS produzindo exatamente o mesmo resultado, sem coluna de
   origem nas tabelas de execução;
8. duração de execução aberta igual em SQL e em Python;
9. fuso da sessão PostgreSQL acompanhando a aplicação;
10. garantias estáticas: Andon sem cálculo, frontend sem indicador industrial,
    execução sem menção a TOTVS/SigmaNEST.

## 7. Conclusão

A cadeia execução → gerencial está consistente e com fonte única declarada por
informação. A única divergência de cálculo encontrada era de relógio, foi
corrigida na fronteira de conexão e está travada por teste. A Etapa 4B pode
começar.
