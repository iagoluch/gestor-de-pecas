# Fundação de dados gerenciais — Gestor de Peças

## Objetivo

Esta fundação existe para que **Apontamento, Consulta, Relatórios, Management View, Auditoria e Rastreabilidade usem a mesma regra de domínio**. A UI não deve recalcular indicadores nem consultar tabelas diretamente.

Fluxo obrigatório:

```text
registro operacional
        ↓
fato industrial canônico
        ↓
regra única de domínio
        ↓
agregação
        ↓
indicador / consulta / relatório
        ↓
drill-down
        ↓
registro de origem
```

## 20 pontos gerenciais consolidados

1. Management View — Visão Geral.
2. Management View — Produção.
3. Management View — Setores.
4. Management View — Perdas.
5. Consulta Operacional.
6. Consulta Operacional — Tempo MES.
7. Produção — Ordens de Produção.
8. Produção — Planejado × Realizado.
9. Análises — OEE.
10. Análises — Paradas.
11. Análises — Setup.
12. Análises — Qualidade.
13. Análises — Cronoanálise.
14. Análises — Capacidade & Gargalos.
15. Auditoria — Inconsistências.
16. Auditoria — Confiabilidade dos Dados.
17. Auditoria de origem e rastreabilidade dos fatos.
18. Rastreabilidade completa.
19. Rateio preservando tempo físico consolidado.
20. Drill-down gerencial até o registro original, com uma única fonte lógica de verdade.

## Regra de quantidade

**Produção realizada = peças boas.**

Refugo e retrabalho são fatos independentes. O histórico legado não deve ser usado como fonte oficial de produção gerencial quando sua `quantidade` representar boas + refugo ou outro valor transacional.

## Tempo MES

`fim - início` é **lead time**, não necessariamente tempo produtivo.

A timeline deve separar pelo menos:

- produção;
- parada;
- setup;
- retrabalho;
- fila;
- atividade sem OP;
- fora de turno.

O motor temporal de OP está em `mes/analytics/timeline.py`. Para períodos novos, a fonte física preferencial é `eventos_estado_recurso`; `mes/analytics/physical_time.py` consolida/adapta a timeline física e também protege o fallback histórico contra duplicação por OPs simultâneas.

## Corte e Nesting

Cada nesting é uma unidade temporal própria. `apontamentos_corte` já registra início/fim por `plano_hash`; a camada gerencial expõe uma linha por nesting contendo:

- tarefa;
- plano/programa;
- sequência do nesting;
- máquina;
- material;
- espessura;
- tempo previsto;
- início real;
- fim real;
- tempo real;
- desvio absoluto e percentual;
- operadores.

Nunca consolidar vários nestings de forma que o gestor perca o tempo individual de cada execução.

## OEE

A regra vigente foi validada para o Gestor de Peças e está centralizada em
`mes.analytics.oee.calculate_oee`:

```text
OEE = Disponibilidade × Performance × FTT
```

O backend **não inventa** componentes quando faltam os fatos necessários. O
contrato retorna `sem_registros`/`dados_insuficientes` em vez de zero. Dados
reais e simulados passam pelo mesmo cálculo; os consumidores apenas formatam.

## Rateio

Tempo físico e tempo atribuído são conceitos distintos.

```text
sessão física: 60 min
OP A: 20 min atribuídos
OP B: 20 min atribuídos
OP C: 20 min atribuídos
```

A soma atribuída deve fechar no tempo físico. Estratégia precisa ser explícita; o sistema não escolhe silenciosamente uma regra industrial. Nos agregados gerenciais, timelines sobrepostas no mesmo recurso são consolidadas fisicamente; se estados diferentes ocuparem o mesmo instante, o período é sinalizado como `desconhecido`/conflitante em vez de o backend escolher um estado arbitrariamente.

## Camadas adicionadas

```text
mes/domain/        tipos e semântica industrial
mes/contracts/     DTOs serializáveis para API/Web
mes/analytics/     timeline, rateio e adapters canônicos
mes/repositories/  protocolos de persistência
mes/services/      serviços de gestão/auditoria/estado/rateio
```

A implementação PostgreSQL atual fica em `app/database/`, enquanto as regras de domínio permanecem independentes da API Web e do repositório concreto.

## Serviços disponíveis para as telas gerenciais

A camada atual expõe contratos independentes do frontend para serem adaptados pela API Web:

- `ManagementService.get_overview()` — resumo para Management View;
- `ManagementService.get_nesting_times()` — tempo individual por nesting de Corte;
- `IndustrialAnalyticsService.time_breakdown()` — composição temporal por setor/recurso;
- `IndustrialAnalyticsService.downtimes()` — paradas e Pareto por motivo/recurso;
- `IndustrialAnalyticsService.setups()` — tempos e eventos de setup;
- `IndustrialAnalyticsService.quality()` — boas, refugo e retrabalho separados;
- `IndustrialAnalyticsService.standard_vs_actual()` — tempo padrão unitário × tempo produtivo real;
- `IndustrialAnalyticsService.chronoanalysis()` — média, mediana, mínimo, máximo e desvio por produto/operação/recurso;
- `IndustrialAnalyticsService.planned_vs_actual()` — fatos planejados disponíveis × execução real;
- `IndustrialAnalyticsService.capacity_configuration()` — configuração de capacidade sem inventar capacidade restante;
- `AuditService.run_period()` — auditoria cruzando fatos, estado físico, turno, calendário e rateio;
- `AuditService.data_quality_summary()` — compatibilidade e contagens sem percentual arbitrário;
- `TraceabilityService.trace_op()` — OP → operações → eventos de quantidade → nestings de Corte → registros de origem;
- `CalendarService.resolve_shift()` / `period_summary()` — turno do recurso, intervalos exatos, exceções e turno que cruza meia-noite sem inventar posição de intervalo;
- `RateioService.registrar()` — sessão física + tempo atribuído conservando o total;
- `ResourceStateService` — estados físicos e atividades sem OP.


## Fronteira para o frontend

`FrontendBackendFacade` agrupa Início, Consulta Operacional, Produção, Análises, Auditoria e Rastreabilidade. `capabilities()` expõe a versão do contrato, fontes canônicas, regras da Manufatura e pendências oficiais. A futura API deve adaptar essa fronteira em vez de duplicar cálculo em endpoints/controllers.
