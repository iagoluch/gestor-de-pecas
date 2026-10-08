# EXPLAIN e volume do recálculo diário do tempo padrão ESTIMADO (08/10/2026)

**Volume SINTÉTICO.** Banco descartável `gestor_pecas_explain_test_tp57`, com schema v57 aplicado só por `apply_migrations`, semeado com `generate_series` e removido com `DROP DATABASE` ao fim. Os números de 2M são **estimativa por extrapolação**, sem medição.

## Conclusão

**Ligar o recálculo diário: sim, mas com ajuste e com teto de volume.** Até cerca de 100k apontamentos na janela de 180 dias ele roda em minutos. **Em 500k ele falha.** Duas causas, ambas fora do banco:

1. `split_concurrent_time` (`mes/analytics/rateio.py:97-102`) é **quadrático** no número de apontamentos por recurso em cada janela de 14 dias.
2. A consulta de fatos estoura o `statement_timeout` de 30 s, e cerca de 70% do tempo dela vai na subconsulta de operadores por evento, dado que o recálculo nem usa.

Não falta índice. Não proponho migration.

## Calibração do volume

- REAL (`gestor_pecas`, v57, leitura com `default_transaction_read_only=on`): **2 apontamentos**, 12 eventos, 66 operações no catálogo e 4.542 OPs PCP. O piloto ainda não gerou volume, então não há base real.
- TEST: 26 apontamentos e 128 eventos, cerca de 5 eventos por apontamento.
- Dimensionamento usado: cerca de 50 recursos apontáveis, 10 a 20 apontamentos por recurso por dia e cerca de 150 dias úteis. Isso dá **75k a 150k apontamentos na janela de 180 dias**. Então 50k é o volume inicial, 500k é cerca de 4x o realista e 2M é estresse.
- Semente por volume N:
  - N apontamentos finalizados na janela, sobre 50 recursos, sendo 7 do Corte (lidos e descartados pelo Python);
  - 5 eventos por apontamento, com 1 operador vinculado a cada evento;
  - N linhas de catálogo e N OPs PCP, com 6.000 chaves (produto, operação, recurso) e 10% delas com tempo do Protheus;
  - 5% dos apontamentos sobrepostos no mesmo recurso, N/2 apontamentos antigos fora da janela, 20 abertos, N/100 sessões com rateio e 300 chaves com tempo manual.
- Servidor: PostgreSQL 17 em Docker (VM de 3,7 GB, `shared_buffers` 128MB, `work_mem` 4MB). Pool real `PostgresConfig` com `statement_timeout` de 30 s, igual ao de produção.

## Volume x tempo

| Apontamentos na janela de 180 d | Fatos por janela de 14 d | EXPLAIN de 1 janela (fatos) | SQL + fetch por janela (real) | Python por janela | `recalculate_estimates` total | RSS de pico | Resultado |
|---|---|---|---|---|---|---|---|
| **50k** (medido, 2 execuções) | 3,9k | 1,39 s | 1,4 a 2,9 s | cerca de 2,4 s | **58,7 a 61,2 s** (CPU Python 31 a 35 s) | 0,55 GB | OK: 37.828 execuções elegíveis, 4.560 chaves estimadas |
| **500k** (medido) | 38,9k | 22,2 s | 20,8 s na 1ª janela; **2ª janela cancelada pelo timeout de 30 s** | **cerca de 350 s** (só a 1ª janela) | **falhou em 401 s** | 0,54 GB após 1 janela; cerca de 4,5 GB projetado com 13 janelas | **FALHA** |
| 100k a 150k (estimativa) | 7,8k a 11,7k | cerca de 3 a 7 s | cerca de 4 a 9 s | cerca de 10 a 22 s | **cerca de 3 a 7 min** | cerca de 0,9 a 1,4 GB | provável OK |
| 2M (estimativa) | 155k | 90 s ou mais (piso linear) | estoura 30 s sempre | cerca de 5.600 s | não termina (cerca de 20 h só de Python) | cerca de 18 GB | FALHA |

Como as janelas foram medidas:

- "Python por janela" é o intervalo entre o fim de uma consulta e o início da próxima: timeline, divisão de concorrência e montagem das amostras.
- O total soma 13 janelas de 14 dias, mais os rateios (menos de 0,3 s) e `substituir_tempos_padrao_estimados`.

## Planos relevantes, resumidos (consulta de fatos, janela 01/07 a 15/07)

Os planos são de `listar_fatos_operacionais_periodo`, que o recálculo chama uma vez por janela.

- **Filtro de período:** usa `Bitmap Index Scan on idx_apontamentos_intervalo` (GiST). Correto, sem seq scan em `apontamentos_operacionais`.
- **Joins:**
  - catálogo: Hash Right Join com seq scan em 50k; em 500k vira `Index Scan catalogo_operacoes_op_pkey`;
  - `catalogo_pcp_ops`: Hash / Parallel Seq Scan, 23 ms em 500k;
  - eventos: `idx_eventos_apontamento_data`;
  - manual vigente: `idx_tempo_padrao_manual_hist_vigencia`.

  Todos adequados.
- **Gargalo, SubPlan 3 (operadores do evento):**
  - plano: `Seq Scan operadores_apontamento` + Hash Join, executado **uma vez por evento**;
  - 50k: 0,045 ms x 19.505 eventos ≈ 0,9 s dos 1,39 s;
  - 500k: 0,079 ms x 194.505 eventos ≈ **15,4 s dos 22,2 s**.

  É linear em eventos e piora com o número de operadores (200 na semente). O `standard_time_samples` não usa esse campo.
- SubPlans 1 e 2 (nome do operador de início e de fim): seq scan na tabela de 200 linhas, 0,8 s em 500k. É escolha do planner por tabela pequena, não índice faltando.
- Os sorts vão para disco (`external merge`, 107 MB em 500k).
- Experimentos em 500k, só medição, sem alterar código:

  | Variante | Tempo | Leitura |
  |---|---|---|
  | `enable_hashjoin=off` | 104,8 s | pior |
  | LATERAL pela PK em operadores | 14,8 s | −33%, ainda perto do teto |
  | `work_mem=64MB` | 21,5 s | sem ganho |

  A correção real é não montar operadores por evento nesta leitura.
- Rateios (`listar_rateios_tempo_periodo`): 0,6 ms em 50k e 3,4 ms em 500k. Irrelevante.

## Lock

- **Lock de processo `_RECALCULATION_LOCK`:**
  - fica preso durante todo o recálculo: cerca de 60 s em 50k e minutos em 100k a 150k;
  - nesse intervalo, o botão manual recebe 409 e o tick diário pula;
  - o lock não bloqueia mais nada.
- **Banco:** só `substituir_tempos_padrao_estimados` abre transação de escrita. Ela faz upsert de uma linha por chave, com 1 round-trip cada, mais um `DELETE`, e segura locks de linha só em `tempo_padrao_estimado`.

  | Chaves | Duração da transação |
  |---|---|
  | 4.560 | 4,6 a 5,9 s |
  | 20.000 | 24,8 s (insert) e 26,3 s (upsert) |

  Um leitor concorrente de `tempo_padrao_estimado` fez cerca de 460 leituras durante a transação de 20k, com **máximo de 37 ms**, sem bloqueio (MVCC). **O tempo de lock no banco não é relevante.** O custo cresce com o número de chaves, não com o de apontamentos.
- **Efeito no processo da API:** o recálculo roda em `asyncio.to_thread` e é CPU-bound em Python (31 s de CPU em 50k, cerca de 350 s por janela em 500k). Ele disputa a GIL com as requisições da API enquanto roda. Além disso, cada janela prende 1 conexão do pool pelo tempo da consulta: até 30 s em 500k.

## Achados

1. **Rateio quadrático (`rateio.py:97-102`).** Para cada trecho elementar entre as bordas de tempo de um recurso, o código percorre todas as OPs do recurso (`any(...)` sobre todos os spans). O custo é O(bordas x OPs) por recurso e janela: no perfil de 50k foram 92 milhões de chamadas do generator.
   - Medido: cerca de 2,4 s por janela em 50k e cerca de 350 s em 500k, ou seja, cerca de 145x para 10x de volume.
   - A função é a mesma do OEE (`_concurrent_production_seconds`), então telas gerenciais com período longo também pagam esse custo.
2. **Memória não limitada pelo fatiamento.** `_recalculate` usa uma única `IndustrialAnalyticsService`, e o `_cache` dela guarda os fatos (com JSON de eventos) de **todas** as 13 janelas, além de rateio e concorrência.
   - Medido: 448 MB liberados ao limpar o cache em 50k, cerca de 9 KB por fato.
   - O fatiamento em `CHUNK_DAYS` resolve o timeout, não a memória.
3. **Consulta de fatos perto do teto de 30 s já em cerca de 40k fatos por janela.** 70 a 75% do tempo vai na subconsulta de operadores por evento, que o recálculo não usa.
4. **Erro enganoso.** O `QueryCanceled` (statement timeout) chega ao recálculo como `DatabaseUnavailableError: "A conexão com o PostgreSQL foi perdida"`. Quem investigar vai procurar problema de rede, não de volume.
5. **Upsert linha a linha.** São cerca de 1,2 ms por chave. Não bloqueia leitores, mas deixa a transação de escrita mais longa do que precisa.
6. **Docstring de `RecalculationJob` cita um "advisory lock do repositório" que não existe** (`substituir_tempos_padrao_estimados` não trava nada). Com mais de um worker da API, o trabalho duplica. O resultado continua idempotente.
7. **Índices: nenhum faltando.** O seq scan em `tempo_padrao_estimado` só acontece com tabela vazia. Os seq scans em `operadores_apontamento` são em 200 linhas.

## Recomendação

**Ligar o recálculo diário: sim, com ajuste.**

- **Pode ligar agora.** O REAL tem 2 apontamentos e, no volume esperado do piloto, ficará muito abaixo de 50k por meses. Medido em 50k: cerca de 1 min, 0,55 GB, transação de escrita de cerca de 5 s sem bloquear leitores.
- **Antes de passar de cerca de 100k apontamentos na janela de 180 dias**, ou de cerca de 150 apontamentos por recurso a cada 14 dias, aplicar nesta ordem:
  - **(a)** Trocar o laço de `split_concurrent_time` por varredura de eventos, ordenando as bordas e mantendo o conjunto ativo: O(n log n). É de analytics/backend e precisa de teste de equivalência numérica, porque também alimenta o OEE.
  - **(b)** Instanciar `IndustrialAnalyticsService` por janela, ou limpar `_cache` a cada janela, em `_recalculate`.
  - **(c)** Usar uma leitura enxuta para as amostras, sem `operadores` por evento e sem nomes de operador, ou pré-agregar os operadores. Isso tira cerca de 70% do SQL por janela.
  - **(d)** Fazer o upsert em lote (`executemany`/pipeline).
- **Paliativo se o volume chegar antes do ajuste:** reduzir `CHUNK_DAYS` para 7. Isso divide por 2 tanto o SQL por janela quanto o custo quadrático por janela, mas não resolve a memória (b).
- **Monitorar:** o evento `tempo_padrao_estimado_recalculado` já registra `execucoes_elegiveis`. Vale alertar quando o recálculo passar de 5 min ou registrar falha.

Nenhuma migration é proposta, porque o gargalo não é índice.

## Depois das otimizações (08/10/2026)

Aplicadas (a) rateio por varredura de eventos (`9c5f712`), (b) um `IndustrialAnalyticsService` por janela e (c) leitura enxuta de fatos (`include_operators=False`, só no recálculo). Mesmo banco descartável, volume **sintético**, mesmas estimativas (hash das linhas de `tempo_padrao_estimado` idêntico antes/depois).

| Volume (180 d) | Antes (b+c) | Depois (b+c) | Memória pico | Consulta de fatos de 1 janela |
|---|---|---|---|---|
| 50k | 34–40 s | 27,7 s | 0,56 → 0,12 GB | 1,6–1,8 s → 1,1 s |
| 100k | 98,1 s | 38,7 s | 1,07 → 0,20 GB | 4,2 s → 0,85 s |
| 500k | falha (timeout de 30 s na 1ª janela, 20,8 s) | falha (1ª janela 11,5 s; 2ª estoura os 30 s) | n/a | 11,9 s (sem timeout) |

- **Até 100k apontamentos na janela de 180 dias o recálculo está dentro do folgado** (39 s, 0,2 GB, cada janela de fatos < 2,5 s). A memória agora é limitada a uma janela, não cresce com as 13.
- **500k continua fora**: a leitura enxuta ajudou (1ª janela 20,8 → 11,5 s), mas uma janela posterior passou de 30 s. Causa não investigada; se o volume chegar perto disso, o próximo passo é `CHUNK_DAYS=7` e depois (d) upsert em lote.
- Equivalência: `tests/test_standard_time.py` (estimativas idênticas entre o fluxo antigo e o novo; cache por janela; analytics padrão ainda lê operadores) e `tests/test_standard_time_postgres.py` (leitura enxuta = completa menos operadores, amostras iguais).
- Banco descartável removido ao final.
