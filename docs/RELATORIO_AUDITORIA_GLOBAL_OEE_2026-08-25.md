# Relatório — Auditoria e correção global do OEE

> **HISTÓRICO.** O banco isolado citado neste relatório foi removido em 27/08/2026 após backup validado. As regras canônicas de OEE permanecem; o ambiente atual de TESTE é `gestor_pecas_test`. Consulte `ROADMAP.md` antes de reproduzir testes.

Data: **25/08/2026**  
Ambiente manual: banco PostgreSQL isolado `gestor_pecas_test_simulacao_residencia_20260824`  
Período validado: **24/08/2026 00:00 a 24/08/2026 08:32**

## Resultado executivo

A regra de OEE que já existia no `ManagementService` foi preservada e promovida
a uma fonte canônica única. O defeito era uma trava de modo: fora de
`simulation_mode`, o serviço nem tentava aplicar a fórmula e devolvia
`dados_insuficientes` com textos de regra pendente, mesmo quando os fatos
necessários estavam presentes.

A cadeia vigente é:

```text
fatos canônicos de tempo, quantidade e tempo padrão
    ↓
mes.analytics.oee.calculate_oee
    ↓
ManagementService.get_overview
    ↓
facade / API / Tela Inicial / KPI explicável / Andon / relatórios / IA
```

Nenhuma fórmula industrial foi substituída, reinterpretada, limitada ou
recalculada no frontend/IA.

## 1. Fonte canônica e implementação encontrada

- Fonte canônica: `mes/analytics/oee.py`.
- Função: `calculate_oee(...)`.
- Orquestrador dos fatos: `ManagementService.get_overview(...)`, em
  `mes/services/management.py`.
- Contrato: `MetricValue`, com `value`, `availability`, `unit` e `reason`.

Entradas da regra preservada:

- segundos por estado físico canônico;
- quantidade boa;
- quantidade de refugo;
- quantidade de retrabalho;
- tempo padrão das peças boas;
- setup, retrabalho e atividade sem OP como tempos produtivos de apoio.

Implementação consolidada, sem mudança da equação existente:

```text
Tempo disponível = produção + setup + retrabalho + atividade sem OP
                  + parada + fila + desconhecido

Tempo trabalhado = produção + setup + retrabalho + atividade sem OP

Disponibilidade = tempo trabalhado / tempo disponível

Tempo produtivo líquido = tempo padrão das peças boas
                         + setup + retrabalho + atividade sem OP

Performance = tempo produtivo líquido / tempo trabalhado

FTT = quantidade boa / (boa + refugo + retrabalho)

OEE = Disponibilidade × Performance × FTT
```

O tempo fora do turno continua fora do tempo disponível. A fila continua no
tempo disponível e fora do tempo operacional auxiliar da simulação. Nenhuma
dessas regras foi alterada.

## 2. Unidade, precisão e ausência de dados

- Unidade pública: percentual na escala **0 a 100**; por exemplo, `82.4`
  significa `82,4%`, não `0,824`.
- Backend: preserva a precisão de ponto flutuante, sem arredondar o valor
  canônico.
- Frontend: formata a exibição com uma casa decimal.
- O valor não é limitado artificialmente a 100%. Portanto, percentuais acima
  de 100% que resultem da regra e dos fatos permanecem visíveis; esta auditoria
  não mudou nem mascarou esse comportamento.
- Sem tempo físico: Disponibilidade fica `sem_registros`.
- Sem tempo trabalhado: Performance fica `sem_registros`.
- Sem quantidades de qualidade: FTT fica `sem_registros`.
- Se apenas parte dos componentes faltar, OEE fica `dados_insuficientes`;
  sem nenhum componente, fica `sem_registros`.

## 3. Motivo real de `dados_insuficientes`

O estado observado era **defeito**, não falta de dados. O banco possuía fatos,
estados físicos, quantidades e tempos padrão. Porém
`ManagementService.get_overview` criava quatro `MetricValue` vazios e somente
os substituía dentro de `if self.simulation_mode`.

Com o mesmo filtro, antes da correção:

- modo normal: OEE `None` / `dados_insuficientes`;
- modo simulação: OEE calculado.

Depois da correção, os dois modos retornam exatamente o mesmo bloco `kpis`.
O modo de simulação identifica apenas a origem dos dados e mantém seus
indicadores auxiliares; não possui outra fórmula de OEE.

## 4. Duplicações e divergências auditadas

| Ocorrência | Classificação anterior | Situação final |
|---|---|---|
| `ManagementService.get_overview` | CANÔNICA, mas presa à simulação | Fórmula extraída para `calculate_oee` e consumida em todos os modos |
| `IndustrialAnalyticsService.quality` | DUPLICAÇÃO do FTT e divergência por modo | Consome o FTT do mesmo `ManagementService` |
| `FrontendBackendFacade.analise("oee")` | DIVERGÊNCIA: placeholder fora da simulação | Consome `overview.kpis.oee` |
| `AndonService` — OEE geral `82,4` | DIVERGÊNCIA / MOCK ativo na simulação | Removido; resumo recebe OEE/A/P/FTT canônicos |
| `AndonService` — KPIs fictícios por recurso | DIVERGÊNCIA / MOCK ativo | Removidos; sem base consolidada por recurso permanece indisponível |
| `ManagementInsightsService` | CONSUMIDOR CORRETO, com texto legado | Mantém o valor canônico; limitação agora fala em falta de dados no filtro |
| Componentes de Performance do KPI Explicável | DIVERGÊNCIA: comparava somente tempo padrão × real por operação | Passou a consumir as bases canônicas `productive_net_seconds` e `worked_seconds`; o comparativo por OP permanece apenas como evidência local |
| React/TypeScript | CONSUMIDOR CORRETO | Continua apenas formatando; nenhuma fórmula de KPI foi encontrada |
| Relatórios e exportações atuais | CONSUMIDOR CORRETO | Continuam consumindo facade/overview; não recalculam |
| Reconciliação da simulação | TESTE/MOCK | Mantida como oráculo independente de teste, fora do runtime |

## 5. Evolução do OEE

A causa da ausência no gráfico foi confirmada no runtime: apesar de o OEE atual
estar disponível, `FrontendBackendFacade.analise("oee")` fixava explicitamente
`points=[]`, e o React sempre renderizava o estado vazio.

O contrato agora separa:

- indicador atual: calculado normalmente quando os fatos do filtro bastam;
- evolução: divide o período em no máximo 31 intervalos e, para cada ponto,
  consome `ManagementService.get_overview(...).kpis.oee`;
- cada ponto também transporta os `MetricValue` canônicos de OEE,
  Disponibilidade, Performance e FTT para consulta detalhada no gráfico;
- a série não contém fórmula própria e declara `calculation_policy=canonical_oee`;
- intervalos realmente sem base são omitidos e contabilizados em
  `missing_points`; uma série incompleta é marcada como `parcial`;
- menos de dois pontos calculáveis mantém a mensagem de dados insuficientes,
  sem invalidar o OEE atual.

No filtro de `27/07/2026` a `24/08/2026 08:32`, o banco de simulação retornou
29 intervalos, 25 pontos calculáveis e 4 intervalos sem base suficiente. O
primeiro ponto foi `86,678%` e o último `113,814%`.

## 6. Valores verificados no banco de teste

Valores brutos do backend para a fábrica, no período validado:

| Indicador | Valor bruto | Exibição Web |
|---|---:|---:|
| OEE | 113.81427050980622 | 113,8% |
| Disponibilidade | 98.02182810368349 | 98,0% |
| Performance | 116.50777081883554 | 116,5% |
| FTT | 99.65957446808511 | 99,7% |

Para o filtro `setor=Corte`, o backend retornou OEE
`232.32323232323236%`, Disponibilidade `100%`, Performance
`233.33333333333334%` e FTT `99.56709956709958%`. Esses valores não foram
limitados nem corrigidos, pois a tarefa determinou preservar a fórmula
validada e os fatos existentes.

## 7. Validação da apresentação

No navegador, com o período congelado explicitamente aplicado:

- Tela Inicial: quatro cards disponíveis e coerentes;
- Evolução do OEE: o estado vazio foi substituído por gráfico SVG responsivo
  quando existem ao menos dois pontos, com eixos percentuais, datas, pontos,
  valor mais recente visível e descrição acessível;
- ao passar o mouse ou focar uma bolinha pelo teclado, o gráfico apresenta um
  tooltip com data, OEE, Disponibilidade, Performance e FTT/Qualidade daquele
  mesmo intervalo; o React apenas formata os valores recebidos;
- KPI Explicável: OEE `113,8%` e componentes `98%`, `116,5%`, `99,7%`;
- Dashboard de Exceções: usa o mesmo overview e preserva as evidências;
- Relatório Gerencial: OEE `113,8%`;
- nenhum texto ativo de fórmula provisória ou exclusiva da simulação.

O componente foi validado por teste Web com três pontos canônicos. Após a
reinicialização do servidor local, a sessão anterior do navegador foi expirada
porque o segredo de desenvolvimento é efêmero; por isso, a confirmação visual
pós-build requer apenas novo login/atualização da página, sem mudança de dados.

## 8. IA Industrial

As tools continuam read-only e não recalculam indicadores:

- `get_factory_status`: recebe OEE, Disponibilidade, Performance e FTT do
  resumo canônico do Andon;
- `get_management_overview`: recebe `overview.kpis`;
- `get_management_insights`: explica os mesmos `overview.kpis`;
- `explain_kpi`: transporta o mesmo `MetricValue` do dashboard.

O teste transversal automatizado confirmou igualdade exata entre facade,
explicador, Andon, relatórios e payload das tools.

Durante o teste real, foi localizada uma redundância exclusiva da projeção da
IA: `explain_kpi` transportava até 25 evidências detalhadas além do valor, dos
componentes, das causas e dos recursos já presentes. A projeção agora mantém
sem alteração `metric`, período, componentes e maior impacto. Para OEE, mantém
até três causas, três recursos e uma amostra determinística de até cinco
evidências, priorizando tipos distintos. Para cada componente isolado, preserva
a principal causa e o principal recurso; evidências detalhadas repetitivas são
omitidas e o truncamento permanece explícito. Ela informa `total`, `returned`
e `truncated`; não recalcula nem corrige nenhum fato.

No snapshot real de teste, o resultado de OEE media 10.435 caracteres antes da
sanitização. A limitação genérica anterior ainda enviava 9.951 caracteres; a
projeção específica final envia 3.394. Performance, já com as bases canônicas
de fórmula e a distinção de desvios locais, envia 2.434 caracteres; FTT, 1.283;
e Disponibilidade, 1.779. Provider, schemas, roteamento, tool calling,
budget e rate limit não foram alterados.

O mesmo teste revelou uma divergência semântica no KPI Explicável de
Performance: o valor do KPI já era canônico, mas os “componentes” mostravam
apenas a comparação local entre tempo padrão e tempo real por OP. O overview
agora publica `kpi_time_bases`, produzido pela própria chamada canônica, e o
explicador usa diretamente `productive_net_seconds` como numerador e
`worked_seconds` como denominador. Tempo padrão e tempo produtivo de apoio são
expostos como partes factuais do numerador. A comparação por OP continua como
evidência, sem virar uma segunda fórmula.

### Perguntas reais à Groq

| Pergunta | Resultado | Tokens |
|---|---|---:|
| Qual é o OEE da fábrica? | SUCESSO — `explain_kpi`; respondeu OEE 113,81%, A 98,02%, P 116,51% e FTT 99,66% | 4.472 prompt + 514 completion = 4.986 |
| Por que o OEE está nesse valor? | SUCESSO — `explain_kpi`; apontou Performance 116,5% como componente que elevou o resultado | 4.474 prompt + 659 completion = 5.133 |
| Como estão Disponibilidade, Performance e FTT? | SUCESSO — três chamadas de `explain_kpi`; respondeu A 98,02%, P 116,51% e FTT 99,66% usando as bases canônicas | 9.256 prompt + 407 completion = 9.663 |
| Qual o OEE do Corte? | SUCESSO — `get_management_insights`; respondeu OEE 232,32%, A 100%, P 233,33% e FTT 99,57% | 4.681 prompt + 439 completion = 5.120 |

[CONFIRMADO] Antes da projeção específica, as perguntas gerais chegavam a
estimativas de 6.521 a 6.687 tokens no segundo passo e eram bloqueadas pelo
budget local de 6.000. Depois da remoção dos detalhes repetitivos, as quatro
perguntas concluíram pelo fluxo real do `AIService`, sem alterar o orçamento. A
terceira usou três rodadas porque pediu três indicadores. Tentativas
intermediárias coincidiram com o limite temporário externo; o backend respeitou
o cooldown e nenhuma repetição automática foi feita.

Respostas textuais obtidas:

> **Qual é o OEE da fábrica?** O OEE registrado foi 113,81%, resultante de
> Disponibilidade 98,02%, Performance 116,51% e FTT 99,66%. A resposta destacou
> a Performance acima de 100% como principal atenção e declarou o ambiente de
> simulação.

> **Por que o OEE está nesse valor?** A resposta explicou que a Performance de
> 116,5% eleva o OEE, enquanto Disponibilidade 98,0% e FTT 99,7% estão próximas
> de 100%; citou a parada por falta de material e os dois refugos como
> evidências, sem recompor a fórmula.

> **Como estão Disponibilidade, Performance e FTT?** “Disponibilidade está em
> 98,02% [...] A Performance apresenta 116,51%, indicando que o tempo produtivo
> líquido superou o tempo trabalhado [...] O FTT (qualidade) está em 99,66%”. A
> resposta distinguiu o desvio desfavorável de uma OP da relação agregada do
> indicador e confirmou que os valores vieram do backend sem recálculo.

> **Qual o OEE do Corte?** A resposta informou OEE 232,32%, Disponibilidade
> 100%, Performance 233,33% e FTT 99,57% no período congelado, com a limitação
> explícita de ausência de metas configuradas.

## 9. Testes executados

- Python completo: **255 testes aprovados**.
- Regressões transversais novas: fórmula, unidade, precisão, ausência real,
  modo normal versus simulação, facade, KPI explicável, Andon, relatórios,
  tools da IA, independência do indicador atual, série canônica por período e
  limite máximo de 31 intervalos.
- Web: **34 testes aprovados**.
- Build: `tsc -b && vite build` concluído.
- Aviso não bloqueante do build: chunk principal acima de 500 kB; já existia
  e não foi tratado por estar fora do escopo de OEE.

## 10. Matriz final de consistência

| Consumidor | Fonte | OEE | Disponibilidade | Performance | FTT | Status |
|---|---|---|---|---|---|---|
| Cálculo canônico | `calculate_oee` | Canônico | Canônica | Canônica | Canônico | OK |
| Tela Inicial | `ManagementService.get_overview` | Mesmo valor | Mesmo valor | Mesmo valor | Mesmo valor | CORRIGIDO |
| Evolução OEE | `ManagementService.get_oee_evolution` → `get_overview.kpis.oee` | Série canônica | Consumida no ponto | Consumida no ponto | Consumido no ponto | CORRIGIDO |
| KPI Explicável | `overview.kpis` + evidências | Mesmo valor | Mesmo valor | Mesmo valor | Mesmo valor | CORRIGIDO |
| Dashboard Exceções | `ManagementInsightsService` | Mesmo valor | Mesmo valor | Mesmo valor | Mesmo valor | OK |
| Andon geral | `overview.kpis` | Mesmo valor | Mesmo valor | Mesmo valor | Mesmo valor | CORRIGIDO |
| Andon por recurso | `ManagementService.get_overview.resource_kpis` → `calculate_oee` | Mesmo cálculo por recurso | Mesmo cálculo por recurso | Mesmo cálculo por recurso | Mesmo cálculo por recurso | CORRIGIDO |
| IA `get_factory_status` | Resumo canônico do Andon | Mesmo valor | Mesmo valor | Mesmo valor | Mesmo valor | CORRIGIDO |
| IA `explain_kpi` | `ManagementInsightsService` | Mesmo valor | Mesmo valor | Mesmo valor | Mesmo valor | OK |
| IA — resposta Groq ponta a ponta | Tools canônicas via `AIService` | Mesmo valor | Mesmo valor | Mesmo valor | Mesmo valor | CORRIGIDO |
| Relatório Gerencial | `FrontendBackendFacade.inicio` | Mesmo valor | Mesmo valor | Mesmo valor | Mesmo valor | OK |
| Relatório Indicadores | `FrontendBackendFacade.analise` | Mesmo valor | Mesmo valor | Mesmo valor | Mesmo valor | CORRIGIDO |

## 11. Arquivos alterados

### Fonte canônica e consumidores

- `mes/analytics/oee.py`
- `mes/analytics/__init__.py`
- `mes/services/management.py`
- `mes/services/industrial_analytics.py`
- `mes/services/frontend_facade.py`
- `mes/services/management_insights.py`
- `mes/services/andon.py`
- `mes/services/ai_tools.py`
- `backend/api/routers/analytics.py`

### Frontend

- `web/src/pages/analytics/AnalyticsPages.tsx`
- `web/src/styles/global.css`
- `web/src/types/api.ts`
- `web/src/types/andon.ts`

### Testes e validação manual

- `tests/test_oee_consistency.py`
- `tests/test_backend_canonical_v11.py`
- `tests/test_industrial_analytics.py`
- `tests/test_management_insights.py`
- `tests/test_web_api.py`
- `tests/test_ai.py`
- `web/src/test/management.test.tsx`
- `web/src/test/andon.test.tsx`
- `tests/oee_preview_api.py`
- `scripts/test_groq_tool_call_real.py`
- `scripts/test_groq_oee_real.py`

### Documentação

- `docs/CONTRATO_FRONTEND_BACKEND_V1.md`
- `docs/MANAGEMENT_DATA_FOUNDATION.md`
- `docs/API_CONTRACTS.md`
- documentos históricos receberam aviso explícito de que a antiga pendência
  de OEE/FTT foi superada.

## Confirmação de escopo

A fórmula validada **NÃO foi substituída**. Não foram alterados migration 14,
apontamento, OP, estados, setup, retrabalho, refugo, rateio, turnos,
autenticação, permissões, provider Groq, parallel tool calling, tool choice,
rate limit ou regras industriais.

## 12. Correção complementar — indicadores por recurso no Andon

### Causa confirmada

Os dados necessários estavam sendo coletados pelo backend, porém
`AndonService` inicializava todos os indicadores dos recursos com
`_metric_unavailable()` e consumia do `ManagementService` somente o resumo
fabril. Portanto, o caractere `—` em todos os cartões não indicava uma falha
geral do banco: a granularidade por recurso era descartada antes da projeção
do Andon.

### Correção

- `ManagementService.get_overview` passou a agrupar, na mesma carga em lote,
  tempo físico consolidado, quantidades canônicas e tempo padrão por recurso.
- Cada agrupamento é entregue à mesma função
  `mes.analytics.oee.calculate_oee` usada no indicador fabril.
- O resultado fica em `resource_kpis`; o `AndonService` apenas associa esses
  valores ao recurso correspondente e não calcula KPI.
- A associação preserva códigos distintos por capitalização e não resolve
  aliases ambíguos por inferência.
- Não foi adicionada consulta por máquina: o Andon continua sem N+1.
- Quando falta tempo físico, quantidade ou tempo padrão, somente os
  componentes sustentados pelos dados são exibidos; o restante continua `—`
  com o motivo explícito vindo do cálculo canônico.

### Resultado no banco congelado de 24/08/2026 às 08:32

- 24 recursos no catálogo do Andon;
- 12 recursos com Disponibilidade calculável;
- 11 recursos com Performance calculável;
- 10 recursos com FTT calculável;
- 10 recursos com OEE completo calculável;
- 14 recursos permanecem sem OEE completo por ausência real de pelo menos um
  componente necessário no período.

Exemplos observados na projeção final, com arredondamento apenas de
apresentação: Laser Ensis 3015 com OEE 232,3%, 1303 com OEE 126,5%, Eurostec
com OEE 149,4% e Fresadora FTV31 com OEE 86,4%. Valores acima de 100% foram
preservados porque são produzidos pela fórmula vigente; esta correção não
alterou, limitou nem reinterpretou o cálculo validado.

### Regressões e execução

- Teste backend confirma OEE, Disponibilidade, Performance e FTT por recurso.
- Teste backend confirma que um recurso parado pode ter Disponibilidade 0%
  sem fabricar Performance, FTT ou OEE ausentes.
- Teste de simulação confirma exatamente as mesmas métricas do fluxo normal.
- Teste de quantidade de consultas confirma ausência de N+1 por máquina.
- Teste Web confirma que o valor recebido é exibido no cartão e no detalhe,
  sem recálculo no React.
- Python: **255/255 testes aprovados**.
- Web: **34/34 testes aprovados**.
- Build Web: concluído com sucesso.
- Servidor local reiniciado e `GET /api/v1/system/health` retornou
  `status=ok`, `database=available`, `schema_version=14` e `api=available`.

A fórmula oficial, as regras industriais, as migrations e os dados do banco
não foram modificados nesta correção complementar.
