# Auditoria de cálculos e projeção — frontend e backend

**Data:** 20/10/2026
**HEAD auditado:** `50a6ad5`
**Árvore de trabalho:** suja (28 arquivos modificados e ~20 novos de sessão em andamento)
**Método:** três auditorias independentes e somente leitura (`oee-engineer`, `backend-engineer`, `frontend-engineer`), com consolidação e reconferência dos achados de topo contra o código nesta sessão.
**Escopo:** cadeia de cálculo industrial, contrato HTTP e projeção no React. Fora do escopo: mapeadores TOTVS/outbox, custos/DRE, autenticação além do que afeta resposta HTTP, e a lógica em andamento dos arquivos WIP.

---

## Veredito

Nenhum P0 na matemática. As regras canônicas (setup produtivo, parada planejada fora do OEE, FTT com retrabalho recuperado, sem demanda 100/0/0) estão implementadas como o `AGENTS.md` determina.

Há, porém, um P0 de exposição: a tela de gestão soma linhas de apontamento como se fossem ordens, e mostra planejado e saldo multiplicados. O erro já acontece com duas operações da mesma OP, não só acima de 200 linhas.

Há dois P1 que corrompem a origem dos dados do Corte (quantidade e data), um P1 de estado envenenado na capacidade, e um P1 de falso conforto na auditoria.

---

## Placar

| # | Gravidade | Achado | Base | Verificação |
|---|---|---|---|---|
| 1 | P0 | `/orders` devolve linha por apontamento; a tela soma como se fosse OP | HEAD | Confirmado nesta sessão |
| 2 | P1 | Corte colapsa repetições de chapa: 3×2 vira 2, não 6 | HEAD | Confirmado nesta sessão |
| 3 | P1 | Corte data toda a produção da tarefa na última chapa | HEAD | Confirmado nesta sessão |
| 4 | P1 | `capacidade_valor` aceita `inf`: grava e derruba o endpoint com 500 | HEAD | Schema confirmado; escrita no banco relatada pelo auditor |
| 5 | P1 | Auditoria afirma "0 em aberto" olhando 200 linhas | HEAD | Confirmado nesta sessão |
| 6 | P2 | Alias de recurso vira "Não informado" e sai da Visão Geral | HEAD | Confirmado nesta sessão |
| 7 | P2 | Rateio aplicado inteiro a cada apontamento da mesma OP+operação | HEAD (latente) | Estrutura confirmada; exposição relatada |
| 8 | P2 | Relatório por OP soma tempo aberto até hoje, não até o fim do filtro | HEAD (latente) | Relatado pelo auditor |
| 9 | P2 | Gráfico arredonda 0,4% para "0%" | HEAD | Confirmado nesta sessão |
| 10 | P2 | "Tempo total medido" é média por recurso | HEAD | Confirmado nesta sessão |
| 11 | P2 | "Ordens" no relatório conta apontamentos | HEAD | Relatado pelo auditor |
| 12 | P2 | "Com tempo padrão" exige padrão **e** real | HEAD | Relatado pelo auditor |
| 13 | P2 | CORS sem `PUT`/`PATCH`, com 4 rotas `PUT` | HEAD | Confirmado nesta sessão |
| 14 | P2 | `queue_areas_for_user` ignora `nivel_efetivo` | WIP | Confirmado nesta sessão |
| 15 | P2 | Paginação em memória sobre até 366 dias | HEAD | Relatado pelo auditor |
| 16 | P2 | `/analytics/oee` calcula o overview duas vezes | HEAD | Relatado pelo auditor |

---

## Achados detalhados

### 1. P0 — `/orders` devolve linha por apontamento e a tela trata como OP

**Base:** HEAD. **Verificação:** confirmado por leitura.

**Evidência**

`mes/services/frontend_facade.py:946-1001`:
```python
for fact in facts:
    planned = fact.get("quantidade_planejada_pcp") or fact.get("quantidade")
    ...
    balance = ManufacturingRules.quantity_remaining(planned, good, scrap)
    items.append({"apontamento_id": fact.get("id"), "op": fact.get("op"), ...})
```

`web/src/pages/production/ProductionPages.tsx:56,64-76`:
```tsx
const query = useApiQuery<PagedOrders>(`/api/v1/orders?...&page_size=${ROW_LIMIT}...`);
const scope = { rows: data?.items ?? [], filterTotal: data?.page.total };
const orderTotals = sumQuantities(scope.rows);
<MetricCard label="Ordens no filtro" value={formatNumber(data?.page.total ?? 0)} />
<MetricCard label="Quantidade planejada" ... detail="Somatório das OPs do filtro" />
```

**O que quebra**

O item é um apontamento, mas `quantidade_planejada` vem de `catalogo_pcp_ops` (quantidade da OP inteira) e se repete em cada linha; `saldo_quantidade` é calculado por linha, antes de qualquer agregação.

Cenário: OP de 100 peças com 3 operações executadas no período e 5 boas em cada.
- "Ordens no filtro" mostra **3** (real: 1).
- "Quantidade planejada" mostra **300** (real: 100).
- "Saldo a produzir" mostra **285** (real: 85).

O mesmo contrato alimenta `OperationsPages.tsx:194-207` ("OPs em andamento"), `ProductionPages.tsx:166-186` (Planejado × Realizado) e `TraceabilityPages.tsx:143-167`. O corte de 200 linhas (`ROW_LIMIT`) agrava, mas o erro não depende dele.

**Correção**

Em `FrontendFacade.ordens_producao`, manter `items` por apontamento (a tabela precisa da linha) e publicar agregados por OP:
```python
"ops_total": len({item["op"] for item in items if item["op"]}),
"totals": {
    "planned": ..., "good": ..., "scrap": ..., "rework": ...,
    "attended": ..., "balance": ...,
}
```
`balance` deve ser calculado **depois** de somar boas/refugo por OP. `page.total` continua sendo contagem de linhas, porque sustenta a paginação — mas deixa de ser rótulo de "ordens". O React passa a ler `ops_total`/`totals` e para de somar linhas.

**Prova**

Fake DB com dois apontamentos da mesma OP (duas operações, PCP `quantidade=100`, 5 boas em cada): `GET /api/v1/orders` deve devolver `ops_total == 1`, `totals.planned == 100` e `totals.balance == 90`. Hoje devolve `page.total == 2` e a tela soma 300.

---

### 2. P1 — Corte colapsa repetições de chapa

**Base:** HEAD. **Verificação:** confirmado por leitura da cadeia.

**Evidência**

`backend/integrations/sigmanest_sqlserver.py:282-287` distingue a chapa física:
```python
chave = (tarefa, programa, chapa, int(repeticao) if repeticao is not None else 1)
```
mas `:316` anexa as peças sem a repetição:
```python
parts=tuple(pecas_por_nesting.get((programa, chapa), ())),
```

`mes/services/sigmanest_sync.py:346-359`:
```python
chave = _linha_hash(tarefa.codigo_tarefa, plano.program_name, peca.codigo_op, peca.produto_codigo)
...
quantidade = max(quantidade, int(atual["quantidade"]))
```

`app/database/database.py:4144`:
```sql
SUM(vinculo.quantidade)::INTEGER AS quantidade
```

**O que quebra**

`SigmaNestPartLine.quantidade` é "peças da chapa" (`MasterPartQty`). O snapshot cria um plano por `RepeatID`, mas o sync grava uma linha por `(tarefa, programa, OP, peça)` e guarda `max`. Três repetições de 2 peças gravam **2**, não 6. O `SUM` de `database.py:4144` lê o valor já colapsado. `mes/services/cut.py:673-677` repete o `max` na fila.

Efeito: peças boas do Corte N× menores (N = chapas/repetições do programa), base de FTT errada e plano × real distorcido.

**Correção**

Incluir `sheet_name` + `repeat_id` na identidade (`_linha_hash` e PK `linha_hash`, `migrations.py:257-258`), uma linha por chapa física com a quantidade daquela chapa. O `SUM` final passa a ser a soma real. Não trocar a leitura para `max` em lugar nenhum. Re-sincronizar com janela ampla para regravar o histórico.

**Prova**

No fixture de `tests/test_sigmanest_planning.py:921-939` (3 repetições × 2 peças), após `sincronizar`, `SELECT quantidade FROM catalogo_sigmanest_ops WHERE codigo_op = '00617399002'` deve retornar **6**; hoje retorna **2**. O teste existente monta o cenário mas não verifica a quantidade.

---

### 3. P1 — Corte data toda a produção da tarefa na última chapa

**Base:** HEAD. **Verificação:** confirmado por leitura.

**Evidência**

`app/database/database.py:4120-4151`:
```sql
MAX(corte.data_fim) AS concluido_em
...
HAVING COUNT(*) FILTER (WHERE corte.status = 'Finalizado') = COUNT(*)
...
WHERE tarefa.concluido_em >= %s AND tarefa.concluido_em <= %s
```

**O que quebra**

A tarefa só conta quando todas as chapas fecham, e a quantidade inteira é atribuída a `MAX(data_fim)`. Duas chapas cortadas em dias distintos:
- filtro do dia 1: `boa = 0`, apesar de a chapa 1 ter sido cortada nele;
- filtro do dia 10: `boa = 2×`, dobrando a produção;
- se a última chapa cair fora do filtro, a produção desaparece do período.

Isso distorce OEE diário, ranking de setor e comparação plano × real.

**Correção**

Projetar a quantidade por chapa (depende do achado 2) e datar cada chapa pelo seu `data_fim`; marcar a tarefa como `PARCIAL` quando só parte das chapas fechou. O critério "todos os planos finalizados" continua válido para dizer que a tarefa fechou, não para datar a produção.

**Prova**

Tarefa com 2 chapas, chapa 1 finalizada no dia 1 e chapa 2 no dia 2: `listar_producao_corte_periodo(dia1, dia1)` deve retornar a quantidade da chapa 1; hoje retorna vazio. `(dia2, dia2)` deve retornar a da chapa 2; hoje retorna o dobro.

---

### 4. P1 — `capacidade_valor` aceita `inf` e envenena o endpoint

**Base:** HEAD. **Verificação:** schema confirmado; escrita e falha de serialização relatadas pelo auditor.

**Evidência**

`backend/api/schemas/common.py:89`:
```python
capacidade_valor: float | None = Field(default=None, ge=0)
```
`backend/api/routers/management.py:311-316` repassa o valor para `vincular_calendario_recurso`, que grava direto no `NUMERIC` (`database.py:5207-5223`).

**O que quebra**

`float` aceita `inf`; `1e400` no JSON vira `inf` e o Pydantic aprova. O PostgreSQL aceita `Infinity` em `NUMERIC`, então o `UPDATE` commita. A serialização da resposta falha (`allow_nan=False`) e o cliente recebe **500** com o dado gravado. Na leitura seguinte, `listar_configuracao_capacidade_recursos` devolve a linha e **todo** o endpoint de capacidade responde 500 até alguém corrigir o banco.

**Correção**

```python
capacidade_valor: float | None = Field(
    default=None, ge=0, le=1_000_000_000, allow_inf_nan=False
)
```
Se o domínio também precisar de guarda no repositório, `math.isfinite` antes do `UPDATE`. A validação de schema resolve o caso HTTP.

**Prova**

`POST /api/v1/management/resource-calendars` com `{"capacidade_valor": 1e400, ...}` deve devolver **422**; hoje devolve 500 e grava `Infinity`. Um `GET` posterior da capacidade deve continuar 200.

---

### 5. P1 — Auditoria afirma "0 em aberto" a partir de 200 linhas

**Base:** HEAD. **Verificação:** confirmado por leitura.

**Evidência**

`web/src/pages/audit/AuditPages.tsx:31,39-50`:
```tsx
const query = useApiQuery<PagedOrders>(`/api/v1/audit/appointments?...&page_size=200`);
const resumo = {
  finalizados: rows.filter((row) => String(row.status ?? "") === "Finalizado").length,
  ...
};
<MetricCard label="Finalizados" value={formatNumber(resumo.finalizados)}
  detail={rows.length ? `${formatNumber(rows.length - resumo.finalizados)} ainda em aberto` : undefined} />
```

**O que quebra**

"Apontamentos" mostra `page.total` real; os outros três cards e o "ainda em aberto" descrevem só a página 1. Se as 200 primeiras linhas estiverem finalizadas e houver 50 abertas depois, a tela escreve **"0 ainda em aberto"** — falso conforto numa tela cuja função é achar exatamente isso.

**Correção**

Remover a inferência de "ainda em aberto" (o contrato não tem contagem por status) e rotular os cards como recorte: `detail={`${rows.length} de ${page.total} apontamentos carregados`}`. Se a contagem por status for necessária, o backend publica `by_status` — não se deduz no cliente.

**Prova**

1 item `Finalizado` + `page.total: 500` → esperar `/1 de 500 apontamentos carregados/` e `queryByText(/0 ainda em aberto/)` nulo.

---

### 6. P2 — Alias do mesmo recurso vira "Não informado" e sai da Visão Geral

**Base:** HEAD. **Verificação:** confirmado por leitura.

**Evidência**

`mes/analytics/physical_time.py:91-96` agrupa pela identidade canônica:
```python
resource_key = str(resolve_resource_identity(segment.resource) or "").strip().casefold()
```
mas `:383-390` rotula o segmento com os nomes crus:
```python
resources = {segment.resource for segment in active_segments if ...}
if len(resources) == 1: return next(iter(resources))
return "Não informado"
```

**O que quebra**

"Laser Ensis" e "LASER1" são a mesma máquina, mas quando os dois estados se sobrepõem o rótulo vira "Não informado". O mesmo recurso aparece como 2–3 em `by_resource`, e no recorte da Visão Geral (`physical_time.py:195-196`) o trecho com alias é **excluído** do total: as horas caem e `excluded_resources` conta o alias como outra máquina.

**Correção**

Passar a identidade/rótulo canônico do grupo para `_sweep_resource` e usar esse rótulo no segmento; reservar "Não informado" para o grupo `__recurso_desconhecido__`.

**Prova**

`consolidate_physical_time` com dois segmentos sobrepostos "Laser Ensis" e "LASER1": esperado **um** item em `by_resource` com o nome canônico e o total preservado; hoje há "Não informado" e/ou dois nomes.

---

### 7. P2 — Rateio aplicado integralmente a cada apontamento da mesma OP+operação

**Base:** HEAD. **Verificação:** estrutura confirmada; exposição relatada (sem rota ativa).

**Evidência**

`mes/services/operational_reports.py:182-184` soma por chave:
```python
rateio_map[key] = rateio_map.get(key, 0.0) + float(allocation.get("segundos_atribuidos_periodo") or 0)
```
e `:236-246` aplica o total em **cada** linha que casa a chave.

**O que quebra**

Dois apontamentos da mesma OP+operação (retorno de retrabalho, reabertura) recebem cada um o total: 600 s viram 1200 s. Atividades sem OP colidem na chave `("", "")` e todas recebem a soma dos rateios sem OP.

Hoje nenhuma rota `backend/` chama `calcular_relatorio_tempos_*` (só testes). É dívida latente: se a tela for religada, o tempo dobra.

**Correção**

Guardar `apontamento_id`/`sessao_recurso_id` no rateio e distribuir pelo overlap real; no mínimo, aplicar uma vez por `(op, operação)` e nunca agregar a chave vazia.

**Prova**

Dois apontamentos da mesma OP+operação e uma sessão de 600 s: o total deve ser 600; hoje é 1200.

---

### 8. P2 — Relatório por OP não recorta o tempo aberto no fim do período

**Base:** HEAD (latente). **Verificação:** relatado pelo auditor.

**Evidência**

`mes/services/operational_reports.py:172` corta no fim do filtro na versão por setor:
```python
agora_periodo = min(self._now(), fim)
```
mas `:405` usa `agora` no último evento da versão por OP.

**O que quebra**

Consultando agosto com uma OP deixada aberta, o relatório soma até hoje (outubro). O "tempo total" do mês infla em semanas e `tempo_aberto` deixa de ser comparável entre períodos.

**Correção**

Usar `agora_periodo` também na versão por OP; se "aberto até agora" for intencional, expor em campo separado e excluir do total do período.

**Prova**

Evento em 01/08/2026, filtro de agosto, `now=20/10/2026`: esperado ~31 dias; hoje ~80.

---

### 9. P2 — Gráfico arredonda participação para 0% e apaga a fatia

**Base:** HEAD. **Verificação:** confirmado por leitura.

`web/src/components/charts.tsx:114` usa `maximumFractionDigits: 0`. Uma fatia de 0,4%, que existe e tem cor na barra, é rotulada "0%". Correção: `maximumFractionDigits: 1` ou `"<0,1%"` abaixo de 0,05.

**Prova:** `parts = [4, 996]` deve renderizar "0,4%"; hoje sai "0%".

---

### 10. P2 — "Tempo total medido" mostra média por recurso

**Base:** HEAD. **Verificação:** confirmado por leitura.

`web/src/pages/operations/OperationsPages.tsx:288,295`:
```tsx
const measuredAverage = resourceCount ? categories.reduce((acc, key) => acc + categoryAverage(key), 0) : measured;
<MetricCard label="Tempo total medido" value={formatHours(measuredAverage)} detail={totalDetail(measured)} ... />
```
O valor é a média por recurso; o total real está no `detail`. Com 10 recursos, "8h" significa 80h de fábrica. Correção: renomear para "Tempo médio medido por recurso".

**Prova:** 2 recursos de 3600 s na mesma categoria → rótulo novo e valor "01:00:00".

---

### 11. P2 — "Ordens" no relatório conta apontamentos

**Base:** HEAD. **Verificação:** relatado pelo auditor.

`web/src/pages/reports/ReportsPages.tsx:162` conta `rows(orders.items).length`, e a lista é de apontamentos. Uma OP com 3 operações infla o card. Correção: contar OPs distintas (`new Set(...map(r => r.op))`) e rotular "OPs distintas".

**Prova:** dois itens com `op: "OP-1"` → esperar 1; hoje mostra 2.

---

### 12. P2 — "Com tempo padrão cadastrado" exige padrão e real

**Base:** HEAD. **Verificação:** relatado pelo auditor.

`web/src/pages/analytics/AnalyticsPages.tsx:644-656` só conta `comparable` quando padrão **e** real existem, mas usa esse número no texto "X com tempo padrão cadastrado". OP com padrão e sem tempo real conta como sem padrão, subestimando a cobertura. Correção: separar `withStandard` (só o padrão) de `comparable` (os dois lados).

**Prova:** um item com padrão e real nulo, outro com ambos → "2 com padrão", 1 comparação efetiva; hoje diz 1.

---

### 13. P2 — CORS não permite `PUT`/`PATCH`, mas existem 4 rotas `PUT`

**Base:** HEAD (agravado no WIP). **Verificação:** confirmado por leitura.

`backend/api/main.py:951`:
```python
allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
```
Rotas `PUT`: `management.py:725` (HEAD), `area_queue.py:101`, `director.py:100,114` (WIP).

Hoje não quebra porque não há cross-origin (Vite faz proxy; produção é mesma origem). No cenário cross-origin que `allowed_origins` existe para cobrir, o preflight recusa reordenar fila e salvar tempo padrão. Correção: incluir `PUT` e `PATCH`.

---

### 14. P2 — `queue_areas_for_user` ignora o nível efetivo (WIP)

**Base:** WIP. **Verificação:** confirmado por leitura.

`app/core/areas.py:57-67`:
```python
def queue_areas_for_user(nivel_atribuido, nivel_efetivo=None):
    atribuido = nivel_atribuido or nivel_efetivo
    if atribuido == "admin": return list(AREAS)
    return list(AREAS_POR_NIVEL.get(atribuido, ()))
```
O segundo argumento nunca é usado. Conta rebaixada para `operador` mantém `queue_areas` na sessão e vê a entrada na UI; a rota devolve 403. Não é bypass — é UI mentindo sobre permissão. Correção: aplicar `can_access_management_web` como `areas_for_user` faz (`areas.py:44-45`).

**Prova:** `assert queue_areas_for_user("lider_usinagem", "operador") == []`; hoje devolve `["usinagem"]`.

---

### 15. P2 — Paginação em memória sobre até 366 dias

**Base:** HEAD. **Verificação:** relatado pelo auditor.

`orders.py:39-46` e `65-71`, `operations.py:110-115`, `audit.py:20-27` e `30-43`, `traceability.py:31-47` carregam o período inteiro e fatiam em Python; a consulta (`database.py:3862-3981`) não tem `LIMIT/OFFSET`. `page=2` custa o mesmo que `page=1`. Não é número errado — é degradação silenciosa. Correção: empurrar `limit/offset` e a contagem para o SQL, e descer os filtros de `status`/`search` antes do `LIMIT`.

---

### 16. P2 — `/analytics/oee` calcula o overview duas vezes

**Base:** HEAD. **Verificação:** relatado pelo auditor.

`backend/api/routers/analytics.py:47-59`: `facade.analise("oee")` já faz `get_overview` e prefetch; em seguida `facade.inicio(...)` chama `get_overview` de novo. Custo dobrado e possibilidade de `value` e `components` virem de leituras diferentes. Correção: montar os dois a partir do mesmo overview.

---

## O que NÃO é bug (não reabrir)

- **FTT com `recovered_*`** (`oee.py:158-162, 219-225`): a recuperação sai só da base do FTT; `good`/Performance continuam físicos. Regra de 19/10/2026, coberta por `tests/test_ftt_retrabalho_recuperado.py`.
- **Boa física inclui a recuperada** (`oee.py:180-183`): só o FTT desconta.
- **"Sem demanda" com 100/0/0** (`oee.py:200-206`): exceção corporativa explícita.
- **Parada planejada fora do OEE** (`management.py:413-418`): remoção na entrada temporal, não em fórmula paralela.
- **Filtro `T23:59:59`**: toda escrita passa por `agora_db`/`normalizar_data_db`, que truncam microssegundos; não perde evento hoje.
- **Somar `previsto_segundos` por chapa**: `apontamentos_corte` tem uma linha por chapa física; somar é correto.
- **IDOR da Qualidade**: fechado com `_exigir_setor` → 404.
- **`/users`**: não devolve `senha_hash`.
- **Erros de API**: não vazam stack trace; handler global cobre.
- **`DirectorRateRequest.valor_hora`**: `StrictFloat` aceita `50` e recusa `"50"`/`true`; conferido no `.venv`.

---

## Ordem de execução sugerida

1. **Contrato de `/orders` + React** (achado 1) — é o que mente hoje para a gestão e contamina quatro telas.
2. **Corte: quantidade e data** (achados 2 e 3) — contamina OEE e FTT na origem; exige migration e re-sync do histórico.
3. **`capacidade_valor`** (achado 4) — barato e elimina estado envenenado.
4. **Auditoria "em aberto"** (achado 5) — remover a inferência é mais seguro que tentar corrigi-la.
5. **Lote P2** — agrupar por arquivo para não abrir dez frentes; `charts.tsx`, `OperationsPages.tsx` e `ReportsPages.tsx` são independentes e podem ir juntos.

---

## Limitações desta auditoria

- Auditoria estática: nenhum dos três auditores executou a aplicação nem a suíte completa. Os cenários de impacto são derivados da leitura do código, não de execução.
- Os achados 8, 11, 12, 15 e 16 foram relatados com `arquivo:linha` mas não reconferidos linha a linha na consolidação; os demais foram confirmados por leitura nesta sessão.
- A árvore de trabalho contém 28 arquivos modificados e ~20 novos de uma sessão em andamento. Os blocos 1 e 2 tocam `management.py` e `operator_flow.py`, que estão nessa lista; implementar sem coordenar com esse WIP vai gerar conflito.
- Não foram auditados: mapeadores TOTVS/outbox, custos/DRE, autenticação além do que afeta resposta HTTP, e a lógica nova de ranking/`manual_queue` (WIP).
