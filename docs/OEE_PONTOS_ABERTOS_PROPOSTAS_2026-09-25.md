# OEE — pontos abertos: como podem ser feitos (proposta)

Data: 25/09/2026 · Base: regra corporativa `corporativa-2026-09-24` (`mes/analytics/oee.py`)
Status: **proposta para validação do Gabriel Fogaça** — nada aqui altera a fórmula corporativa.

## Contexto do que já foi feito nesta rodada

1. **OP programada** = operação do roteiro TOTVS vigente (`catalogo_operacoes_op` ativa + OP ativa em
   `catalogo_pcp_ops`) cujo recurso é o recurso em questão e que ainda não foi apontada (apontamento
   `Aguardando` não conta). Quando o recurso fica sem execução (fim da última OP, fim do intervalo, retorno
   do turno), ele entra em **fila com essa OP** (QUEUE, tipo `op_programada`) em vez de "Recurso sem
   demanda" (NO_DEMAND). Ordem de escolha: prazo de entrega, emissão, OP, sequência.
2. **Vigência dos turnos** (migration 50): cada alteração em `parametros_turno` vira uma versão datada em
   `parametros_turno_historico`. `_fora_do_turno` decide um instante com o turno que valia nele.

---

## 1. Performance do Corte

**Hoje:** a produção do Corte vem do nesting (SigmaNEST) e entra como `good_without_standard`
(`mes/services/management.py`), então a Performance do Corte fica "não configurada".

**Fonte disponível:** `catalogo_sigmanest_planos_corte.tempo_previsto_segundos`, que é o tempo previsto
de corte **do plano**, não o tempo de uma peça.

| Opção | Como | Prós / contras |
|---|---|---|
| A. Tempo previsto do plano como run padrão | Para cada plano cortado, `tempo_padrão = tempo_previsto_segundos × (chapas cortadas / chapas do plano)`; P = Σ padrão / tempo trabalhado | Dado já existe e é específico da máquina. O contra é que o previsto do SigmaNEST é uma estimativa do CAM, não um padrão de engenharia. |
| B. Manter NOT_CONFIGURED | Nada muda | É honesto, mas o OEE do Corte fica permanentemente sem P. |
| C. Tempo padrão por peça vindo do TOTVS | Igual à manufatura | Não existe hoje para o Corte (ver item 3). |

**Recomendação:** **A**, marcada como origem `sigmanest_previsto` no trace (`good_with_standard` separado
por origem), para que a tela mostre "Performance baseada no previsto do nesting". Precisa de uma decisão do
Gabriel: o previsto do CAM é aceito como padrão corporativo?

## 2. Semântica do FTT

**Hoje:** FTT = boas / (boas + refugo + retrabalho), com a peça como unidade.

**Pontos a confirmar:**
- **Retrabalho conta como "não primeira vez"?** Hoje, sim: a peça retrabalhada sai do numerador mesmo
  que depois fique boa. Esse é o conceito clássico de *First Time Through*. Recomendação: **manter**.
- **A peça retrabalhada que depois vira boa conta duas vezes?** Ela não pode entrar em "boas" de novo.
  Proposta: o retrabalho é lançado só como retrabalho, e a peça recuperada **não** volta como boa no mesmo
  FTT. Isso precisa de uma regra explícita no apontamento de qualidade (hoje depende do operador).
- **Qual é a unidade no Corte?** Peça nestada, e não chapa.

**Recomendação:** documentar as três regras acima como `FTT_RULE` dentro do trace do OEE. A fórmula não muda.

## 3. De onde vem o tempo padrão

**Hoje:** `catalogo_operacoes_op.tempo_medio_segundos` chega **NULL** do TOTVS (a ingestão não inventa esse
valor). `definir_tempo_padrao_operacao` preenche um valor sintético (`tempo_padrao_sintetico`) só onde ele
está ausente, e só para simulação. No REAL, a Performance fica "não configurada".

| Opção | Como | Prós / contras |
|---|---|---|
| A. TOTVS SG2 (roteiro) | `G2_TEMPAD` / `G2_LOTEPAD` (+ `G2_SETUP` à parte) na operação. Trazer no pull da OP (GPOPSYNC, já homologado) ou numa consulta de roteiro. | É a fonte corporativa e única. Depende de a engenharia manter o SG2 preenchido e de um ajuste no fonte AdvPL (repo Protheus-AdvPL). |
| B. Cadastro interno no Gestor | Tela de tempo padrão por produto/operação | Rápido de fazer, mas cria uma segunda fonte de verdade. |
| C. Tempo médio histórico | Mediana dos apontamentos | Não é um padrão: mede o real contra o próprio real, e a P tende a 100%. |

**Recomendação:** **A**. Levantar com o PCP se o SG2 tem `G2_TEMPAD` preenchido e, se tiver, incluir no
GPOPSYNC `tempo_padrao = G2_TEMPAD / G2_LOTEPAD` (segundos por peça). Enquanto o dado não existir, manter
NOT_CONFIGURED, e nunca usar a opção C.

## 4. Consolidação da exceção "período todo sem demanda"

**Hoje:** um recurso com o período inteiro sem demanda dá 100/0/0 (regra fechada, não reabrir). No
consolidado do setor/fábrica, as bases são somadas e o recurso sem demanda fica segregado
(`SOMA_DE_BASES_SEM_DEMANDA_SEGREGADO`, status `PENDENTE_HOMOLOGACAO` em `management.py`).

**Proposta:** homologar como está:
- o consolidado soma **bases** (tempos e quantidades), nunca faz média de percentuais;
- recurso só com NO_DEMAND contribui com zero para as bases, então não puxa o setor para baixo nem para cima;
- a tela lista esses recursos em `no_demand_exception_resources` ("sem demanda no período").

Falta só a aprovação formal do Gabriel para trocar o status para `HOMOLOGADO`.

**Efeito da OP programada:** com cerca de 1.915 OPs ativas no catálogo TOTVS, a maioria dos recursos no TEST
tem OP pendente (DOBRA3, LASER1, SOLDA4, PINT.L; só SERRA4 ficou sem). "Sem demanda" vai ficar raro e
**a fila vai crescer**. QUEUE fica fora de A/P/FTT, então o OEE não piora, mas o tempo de fila aparece.
Se o catálogo tiver OPs antigas "esquecidas" (não canceladas no TOTVS), elas vão manter recursos em fila.
Sugestão: combinar com o PCP uma política de encerrar OPs mortas, ou aplicar um corte por prazo de entrega
no filtro (decisão do Gabriel).

## 5. Versão da regra/calendário no histórico

**Hoje:** o trace do OEE carrega `rule_version` quando é calculado, mas `eventos_estado_recurso` não guarda
qual regra ou calendário valia. O turno agora tem vigência (migration 50).

**Proposta (aditiva):**
1. Snapshot/relatório de OEE gravado passa a guardar `OEE_RULE_VERSION` + `calendario_versao` (o maior
   `parametros_turno_historico.id` vigente no fim do período). Um recálculo futuro sabe com que regra o
   número foi feito.
2. `AuditService` (`mes/services/audit.py`) e `ShiftBoundaryService` passam a usar
   `load_manufacturing_rules(db, vigente_em=instante)` para períodos passados. Hoje só `_fora_do_turno`
   faz isso.
3. Não é preciso colocar uma coluna em cada evento: a vigência pode ser derivada pelo `data_hora` do evento.

## Lacunas conhecidas desta rodada

- **OP sincronizada com o recurso já em "sem demanda":** o estado não muda na hora, só no próximo evento
  (fim de intervalo, retorno do turno ou fim de OP). Para mudar na hora, seria preciso um gancho no
  sync do catálogo.
- **Precedência do roteiro:** a OP programada não verifica se a operação anterior do roteiro já terminou.
- **Apontamentos legados** com `numero_operacao` NULL não excluem a operação do catálogo (ela pode
  aparecer como programada mesmo já feita).
- **Vigência retroativa:** as versões de turno anteriores à migration 50 foram retroagidas a 1900-01-01
  com o valor atual (não há registro do que valia antes).
