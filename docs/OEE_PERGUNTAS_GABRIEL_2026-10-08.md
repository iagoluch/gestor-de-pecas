# OEE — 3 decisões que dependem do Gabriel Fogaça

Data: 08/10/2026 · Base: `docs/OEE_PONTOS_ABERTOS_PROPOSTAS_2026-09-25.md` · Regra corporativa `corporativa-2026-09-24`

**O que muda para ele:** nada da fórmula corporativa é alterada. São 3 respostas de "sim/não" (ou "A/B"). Com elas, o Gestor passa a mostrar Performance do Corte e fecha a consolidação do OEE.

**Já resolvido (não precisa responder):** o tempo padrão das peças sem `G2_TEMPAD` (hoje 0,01) é preenchido pela aba **Manufatura** do Gestor. O item SG2/G2_TEMPAD está concluído.

---

## 1. Performance do Corte: o previsto do SigmaNEST vale como tempo padrão?

**Situação:** a produção do Corte vem do nesting (chapa cortada), mas não existe tempo padrão por peça para o Corte. Hoje a Performance do Corte aparece como "não configurada".

**O que temos:** o SigmaNEST informa o **tempo previsto de corte do plano** (`tempo_previsto_segundos`).

**Como ficaria (opção A, recomendada):**
- tempo padrão do plano = tempo previsto × (chapas cortadas ÷ chapas do plano)
- Performance = soma dos tempos padrão ÷ tempo trabalhado
- a tela mostra "Performance baseada no previsto do nesting", separada das demais

**Pergunta ao Gabriel:** o tempo previsto do SigmaNEST (estimativa do CAM) é aceito como padrão corporativo para o Corte?
- **Sim** → implemento a opção A.
- **Não** → Performance do Corte continua "não configurada" até existir um padrão de engenharia.

---

## 2. FTT: confirmar 3 regras

FTT = boas ÷ (boas + refugo + retrabalho). A fórmula não muda; faltam as regras de contagem:

| # | Regra proposta | Resposta |
|---|---|---|
| a | Peça que foi para retrabalho **sai** do numerador do FTT, mesmo que depois fique boa (conceito clássico de First Time Through) | Sim / Não |
| b | A peça recuperada **não volta como boa** no mesmo FTT (senão conta duas vezes) | Sim / Não |
| c | No Corte, a unidade do FTT é a **peça nestada**, não a chapa | Sim / Não |

Com as 3 respostas, gravo a regra no trace do OEE (`FTT_RULE`) para a tela explicar o número.

---

## 3. Consolidação por soma de bases: homologar?

**Regra atual (já aplicada no sistema):**
- o consolidado do setor e da fábrica **soma bases** (tempos e quantidades); nunca faz média de percentuais;
- recurso com o período inteiro sem demanda (100/0/0) contribui com **zero** para as bases: não puxa o setor para cima nem para baixo;
- a tela lista esses recursos em "sem demanda no período".

**Pergunta ao Gabriel:** aprova essa forma de consolidar?
- **Sim** → troco o status de `PENDENTE_HOMOLOGACAO` para `HOMOLOGADO`.
- **Não** → ele diz como quer (ex.: média ponderada por outra base) e eu ajusto.

---

## Respostas recebidas 19/10/2026

Manufatura (Gabriel Fogaça), regra corporativa `corporativa-2026-09-24` (fórmula inalterada):

1. **Sim** — previsto do SigmaNEST vira tempo padrão do Corte (opção A). Implementado em
   `mes/services/management.py` (`_cutting_standard`): soma o previsto das chapas cortadas no período
   (cada chapa física tem o próprio previsto, o que equivale a previsto × cortadas ÷ chapas do plano).
   Trace com `standard_origin: sigmanest_previsto` e rótulo "Performance baseada no previsto do nesting".
   Chapa cortada sem previsto deixa a tarefa como "sem tempo padrão".
2. **Sim / Sim / Sim** — (a) retrabalho fica fora das boas de primeira; (b) a recuperação é registrada,
   mas não soma outra boa, e cada peça entra uma vez na base; (c) no Corte a unidade é a peça
   efetivamente cortada. Gravado como `ftt_rule` no trace (`mes/analytics/oee.py`).
3. **Sim** — consolidação homologada (soma de bases, ocupação física sem duplicar OPs simultâneas,
   recurso todo sem demanda = zero e listado, estado desconhecido = disponível não trabalhado).

---

## Mensagem pronta para enviar

> Gabriel, preciso de 3 respostas para fechar o OEE no Gestor:
> 1. O tempo previsto do SigmaNEST pode ser o tempo padrão do Corte para a Performance? (sim/não)
> 2. FTT: (a) retrabalho sai do numerador mesmo se depois ficar bom; (b) a peça recuperada não volta como boa; (c) no Corte a unidade é a peça nestada. De acordo com as 3? (sim/não em cada)
> 3. O consolidado de setor/fábrica soma as bases (não faz média de percentuais) e recurso totalmente sem demanda entra com zero. Pode homologar? (sim/não)
>
> A fórmula corporativa não muda. O tempo padrão das peças com 0,01 já é tratado pela aba Manufatura.
