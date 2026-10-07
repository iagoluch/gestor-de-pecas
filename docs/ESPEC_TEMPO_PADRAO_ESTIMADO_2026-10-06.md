# Especificação curta — Tempo padrão estimado pelo Gestor (06/10/2026)

**Status (06/10/2026, fim do dia):** backend e aba de gestão implementados e testados, **não commitados, migrations 56/57 não aplicadas ao REAL**; revisão R3 feita e correções em andamento. Decisões A/B/C fechadas: **P25**, Performance estimada **separada** da oficial, **sem retroativo** (implementado na migration 57: `vigente_desde` TIMESTAMP por versão do manual e por chave estimada; vigência por **instante** (comparada com o início do apontamento, sem limitação de dia); limitação: chave estimada que perde amostras e é apagada some também dos períodos já fechados na visão "estimada"). A edição manual deixou de ser "fora de escopo": existe a aba "Tempo padrão" (níveis `manufatura`/`admin`, contas `gabriel.fogaca` e `lucas.santos`), prioridade Protheus > manual > estimado, Corte nunca recebe manual/estimado. O texto abaixo é a proposta original. **Risco:** R3 (regra industrial/OEE + schema). **Owners:** `oee-engineer` + `database-engineer`; QA + reviewer antes de commit.

## 1. Problema
~90% das atividades chegam do Protheus (`SIGAPCP`/`ProductionOrder`, `<TimeResource>`) com 0,01 = "não configurado" (responsabilidade do PCP, sem ação possível). O mapper já converte 0,01 em NULL (`mapper.py::_standard_seconds_per_piece`), então a operação fica sem tempo padrão e a Performance do OEE não a considera (`management.py:116` acumula `good_without_standard`; `industrial_analytics.py:248` deixa `expected = None`). Hoje esse volume é invisível para a Performance.

## 2. Objetivo
Quando uma peça/operação **sem tempo do Protheus** for produzida de novo, o Gestor usa um tempo padrão **estimado** a partir das próprias execuções boas anteriores, sempre rotulado como estimado, nunca sobrescrevendo o do Protheus.

## 3. Decisões (as marcadas ◆ precisam do Iago)
1. **Método:** estatística robusta, sem ML. Mediana dos segundos/peça das execuções elegíveis. Percentil 25 só como alternativa, ver ◆A.
2. **Chave:** `(produto_codigo, numero_operacao, codigo_recurso)`. Todos já existem em `apontamentos_operacionais`/`catalogo_operacoes_op`.
3. **Execução elegível** (todas as condições):
   - `status` finalizada, `quantidade_boa >= 1`;
   - sem parada nem setup no intervalo (a timeline já separa `EventCategory.PRODUCTION`);
   - fora de rateio entre OPs simultâneas (`time_source` ≠ `rateio*`), porque o tempo dividido não é capacidade;
   - segundos/peça = tempo de PRODUÇÃO ÷ `quantidade_boa`; tempo de setup fica de fora.
4. **Amostra mínima:** N=5 execuções elegíveis (parâmetro, não constante solta). Abaixo disso, continua sem padrão. Outliers fora de 1,5×IQR são descartados antes da mediana.
5. **Prioridade da fonte:** valor do Protheus (`catalogo_operacoes_op.tempo_medio_segundos`) > estimado > nada. Se o Protheus passar a mandar valor real, o estimado deixa de ser usado sem apagar histórico.
6. **Onde guardar:** tabela nova `tempo_padrao_estimado(produto_codigo, numero_operacao, codigo_recurso, segundos_por_peca, amostras, calculado_em, janela_inicio, janela_fim)`, PK na chave. Não reutilizar a coluna do catálogo: a reimportação já faz `COALESCE(EXCLUDED, atual)` (`totvs_repository.py:521`), então um estimado ali seria tratado como valor do Protheus e perderia a origem.
7. **Cálculo:** job idempotente (recalcula por chave quando entra execução elegível nova, ou 1x por dia). Calcula por leitura, sem alterar apontamento.
8. **Consumo:** a consulta de fatos (`database.py:~3775`) passa a devolver `tempo_padrao_segundos` e `tempo_padrao_fonte` (`protheus` | `estimado` | NULL) com `COALESCE(c.tempo_medio_segundos, e.segundos_por_peca)`. Os dois consumidores (`management.py`, `industrial_analytics.py`) só leem as colunas novas; a lógica de Performance não muda.
9. **UI/relatório:** onde a Performance aparece, o rótulo "estimado" quando a fonte for estimada; tooltip com amostras e janela. Sem botão novo e sem fricção para operador.

## 4. Decisões abertas
- **◆A Mediana ou percentil 25?** Mediana mede "como a peça costuma sair" e tende a Performance ≈ 100% no longo prazo. P25 mede "capacidade demonstrada" e mantém a Performance informativa, mas pune quem ficou na mediana. Recomendo **P25**.
- **◆B Performance estimada entra na consolidação do OEE do setor/fábrica?** Recomendo **mostrar separada** (Performance "oficial" só com Protheus + linha "estimada") por 1 mês, e só depois decidir consolidar. Se entrar direto, os números históricos mudam retroativamente.
- **◆C Retroativo?** Recomendo **não** recalcular períodos já fechados; o estimado vale só para leitura nova (a janela da leitura define se usa).

## 5. Fora de escopo
Machine learning, previsão por lote/material/operador, qualquer edição manual do tempo (segunda fonte de verdade), mudança no mapper/GPOPSYNC, tela de cadastro.

## 6. Critérios de pronto
- Teste: Protheus presente → usa Protheus mesmo com estimado existente; Protheus NULL + estimado → usa estimado e marca fonte; < N amostras → NULL; setup/parada/rateio não entram; reimportação com 0,01 não apaga o estimado; Protheus real posterior vence.
- Migration numerada com rollback documentado; EXPLAIN da consulta de fatos em banco descartável com volume sintético rotulado (ver `procedimento-explain-banco-descartavel`).
- Dados reais: o REAL acabou de ser promovido (06/10) e o TEST tem 26 apontamentos, quase todos simulados. **Sem produção real acumulada o estimado fica vazio**; a validação final só é possível depois de algumas semanas.
