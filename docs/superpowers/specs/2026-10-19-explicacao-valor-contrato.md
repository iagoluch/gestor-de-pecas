# Explicação clicável — contrato para números que não são tempo (Fases 2/3)

Pedido do Iago (19/10/2026): "literalmente tudo que não é clicável quero que seja clicável e que tenha uma explicação do porquê aquilo está assim."
Segue o desenho de 16/10 (`2026-10-16-explicacao-clicavel-design.md`): só explica, não muda fórmula; a explicação nasce do mesmo cálculo do número; sem botão em TV; sem aba nova; painel lateral único.

## Resposta de valor (`kind: "value"`)

Mesmo endpoint `GET /api/v1/management/explicacao?metric=<id>&<filtros analytics_filter>`.
Ids novos: `qtd.*` (peças), depois `qld.*`, `kpi.*`, `custo.*`, `corte.*`, `padrao.*`, `integ.*`.
O despacho é por prefixo: `tempo.*` continua no `MetricExplanationService`; os demais vão para `ValueExplanationService` (`mes/services/value_explanation.py`). Id desconhecido = 422 `unknown_metric` (igual hoje).

```json
{
  "kind": "value",
  "metric": "qtd.refugo",
  "label": "Refugo",
  "unit": "pcs",            // "pcs" | "pct" | "brl" | "count" | "hours" | "text"
  "value": 12.0,            // o número clicado, calculado pelo MESMO caminho da tela
  "reason": "frase simples: por que está assim",
  "rule": "fórmula/regra aplicada, em português",
  "children": [Node],       // setor → recurso → registro
  "excluded": [{"label": "...", "value": 3.0, "reason": "..."}],
  "reconciliation": {"ok": true, "sum": 12.0, "diff": 0.0},
  "calculated_at": "2026-10-19T14:02:11",
  "truncated": false,
  "notes": ["avisos de divergência conhecida, em frase simples"]
}
Node = {"kind": "sector|resource|op|event|part|input|group", "label": "...", "value": 5.0,
        "children": [Node], "detail": {"chave": "valor"} | null, "truncated": false}
```

- `detail` de um registro folha: só o que existe (id do registro, OP, operador, data/hora, motivo, origem). Nunca inventar campo.
- `kind: "group"` = agrupamento que não é setor (tipo ou gravidade da inconsistência); a soma dos filhos fecha com o valor.
- `kind: "input"` = entrada de fórmula (ex.: numerador e denominador de uma taxa); a soma dos filhos NÃO precisa bater com o valor, e a `reconciliation` descreve a fórmula (`sum` = resultado recomposto das entradas).
- Nome de operador: cortado para quem não é gestão (reusa `redact_operator_names`; estenda se `detail.operador` precisar).
- Corte por tamanho: máx. 200 folhas por recurso, `truncated: true`, total sempre correto.

## Lote 1 — peças (eventos de quantidade)

Fonte: `eventos_quantidade_producao` pelo MESMO caminho de `ManagementService.get_overview` (`_load_quantity_events`, `production.good/scrap/rework`, `source`). Se a visão geral cair no fallback (`apontamentos_operacionais_fallback`), a explicação usa o mesmo fallback e diz isso em `notes`.

| id | unit | valor |
|---|---|---|
| `qtd.boa` | pcs | boas no período (setor → recurso → evento) |
| `qtd.refugo` | pcs | refugo (setor → recurso → evento, com motivo) |
| `qtd.retrabalho` | pcs | retrabalho (idem) |
| `qtd.taxa_refugo` | pct | refugo ÷ (boa + refugo); entradas boa e refugo |
| `qtd.ftt` | pct | boa ÷ (boa + refugo + retrabalho); entradas as três (nota: base diferente da taxa de refugo) |

Notas obrigatórias (divergências conhecidas, mostrar e NÃO corrigir):
- taxa de refugo ignora retrabalho; FTT inclui.
- os totais da Visão Geral/Produção realizada vêm dos eventos do período; as tabelas "Produção > OPs" e "Planejado x Realizado" somam os apontamentos por OP (não restritos ao período) — podem divergir.

## Lote 2 — qualidade e auditoria (`qld.*`, `mes/services/quality_explanation.py`)

| id | unit | fonte do valor | árvore |
|---|---|---|---|
| `qld.boa` / `qld.refugo` / `qld.retrabalho` | pcs | `IndustrialAnalyticsService.quality()["totals"]` (Análises > Qualidade) | setor → recurso → lançamento, com os MESMOS eventos de `_quantity_events` |
| `qld.auditoria.total` | count | `AuditService.run_period()["count"]` (Alertas e Auditoria) | gravidade → tipo → recurso → registro |
| `qld.auditoria.critico` / `.erro` / `.aviso` | count | `run_period()["by_severity"][nível]` | tipo → recurso → registro |

Notas obrigatórias: `qld.boa` não inclui as peças boas do Corte (a Visão Geral inclui; pode ser menor que `qtd.boa`); fonte reserva quando não há lançamentos de quantidade; retrabalho parcial; resumo por motivo no refugo/retrabalho. Na auditoria: sem percentual de confiabilidade (sem fórmula oficial); lacunas de calendário são diagnóstico, não alerta; rateio só conferido sem filtro de OP/operação; fonte reserva do estado físico; a tabela da Auditoria mostra 200 linhas, os cartões contam todas. Gravidade não reconhecida entra só no Total (grupo próprio) e vai para `excluded` nos cartões por nível.

## Totais somados no navegador (Produção > OPs, Planejado x Realizado)

Não passam pelo backend: o painel recebe a explicação já montada no navegador com as MESMAS linhas que geraram a soma (sem segundo cálculo). Mostrar: uma linha por OP (valor da coluna), `reconciliation` = soma das linhas = número do cartão, e SEMPRE a nota "Soma das N linhas carregadas; o filtro tem M no total" quando N < M (limite de 200). Sem chat de IA nesses (não há métrica no servidor).
Fórmulas a explicar, tal como estão hoje: planejada = soma de `planned`; boa; atendida = boa + refugo; saldo = max(0, planejada − boa − refugo) por linha (ignora retrabalho); % atendida = atendida ÷ planejada; "% do planejado" do cartão Peças boas = só boas.
