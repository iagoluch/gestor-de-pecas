---
titulo: Análises - Tempo padrão x real
grupo: Análises
ordem: 74
rotas: /analises/tempo-padrao-real
---

A tela **Análises — Tempo padrão** compara o tempo que a operação deveria levar com o tempo que levou de verdade. Texto da tela: "Tempo padrão e execução real por OP/operação com fonte temporal identificada."

Usa a barra de filtros do topo. Veja [Filtros globais](topico:04-filtros-globais).

## Como a conta é feita

Para cada apontamento (OP + operação):

1. **Padrão estimado** = tempo padrão de 1 peça × peças boas.
2. **Tempo real** = tempo de produção medido na linha do tempo da máquina.
3. **Desvio** = tempo real − padrão estimado.
4. **Desvio %** = desvio ÷ padrão estimado.

Exemplo: padrão 2 min por peça, 30 peças boas: padrão = 60 min. Levou 75 min. Desvio = +15 min = +25%.

O tempo padrão usado aqui é só o oficial, que vem do Protheus (um tempo estimado pelo sistema não entra nesta conta). Sem padrão cadastrado, a linha não tem desvio. Sem peças boas, também não. Sem eventos de máquina, não há tempo real.

## Cartões

| Cartão | Significado |
|---|---|
| Comparações | Quantas linhas. Detalhe: "N com tempo padrão cadastrado" (aqui conta só as que têm padrão e tempo real). Clicável. |
| Tempo padrão acumulado | Soma do padrão das linhas comparáveis. "Não configurado" se nenhuma linha puder ser comparada. |
| Tempo real acumulado | Soma do tempo real dessas mesmas linhas. "Dados insuficientes" se nenhuma linha puder ser comparada. |
| Desvio do padrão | (real − padrão) ÷ padrão, em %. O detalhe mostra a diferença em horas. Vermelho se passou do padrão. |

Só entram nos acumulados as linhas com padrão **e** tempo real.

## Tabela "Desvios por OP/operação"

| Coluna | Significado |
|---|---|
| OP | Clique para abrir em Rastreabilidade. |
| Operação / Produto | Qual serviço. |
| Recurso real | Máquina onde foi feito. |
| Peças boas | Quantidade boa. |
| Padrão estimado | Tempo esperado. |
| Tempo real | Tempo medido. |
| Desvio / Desvio % | Diferença; sinal + significa acima do padrão. |
| Fonte | De onde veio o tempo real. "—" quando falta padrão ou peça boa na linha: Padrão estimado, Desvio e Desvio % ficam vazios. |

Fontes do tempo real:

- **Rateio de tempo**: sessão de rateio entre OPs.
- **Linha do tempo da OP**: tempo de produção da OP.
- **Linha do tempo da OP, dividido igualmente**: duas ou mais OPs rodaram juntas na mesma máquina e o tempo foi dividido, para não passar do tempo físico.
- **Dados insuficientes**: não há eventos para medir.

## Problemas comuns

| Situação | O que fazer |
|---|---|
| "Não configurado" | Nenhuma linha tem tempo padrão do Protheus com tempo real medido. Confira o tempo padrão do produto no Protheus. |
| "Dados insuficientes" | Sem eventos de máquina no período. |
| Desvio sempre negativo | O padrão pode estar folgado; revisar. |

Veja também: [Cronoanálise](topico:75-analises-cronoanalise) e [Melhoria Contínua](topico:68-melhoria-continua).
