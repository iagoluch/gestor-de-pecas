---
titulo: Análises - Cronoanálise
grupo: Análises
ordem: 75
rotas: /analises/cronoanalise
---

A tela **Análises — Cronoanálise** mostra quanto tempo cada peça realmente leva, por produto, operação e máquina. Texto da tela: "Distribuição do tempo real por peça, agrupada por produto, operação e recurso."

Usa a barra de filtros do topo. Veja [Filtros globais](topico:04-filtros-globais).

## De onde vem

Cada execução com peças boas vira uma **amostra**: tempo real ÷ peças boas. As amostras são agrupadas por produto + operação + recurso. É o mesmo tempo real da tela [Tempo padrão × real](topico:74-analises-tempo-padrao-real).

## Cartões

| Cartão | Significado |
|---|---|
| Grupos analisados | Quantos grupos. Detalhe: total de execuções medidas. |
| Ciclo médio por peça | Média de todos os grupos, ponderada pelo número de amostras. |
| Maior variação | O grupo com maior desvio padrão (mais irregular). |
| Ciclo mais lento | O grupo com maior média por peça. |

Sem dados: "Dados insuficientes".

## Gráfico e tabela

- **Média real por peça**: barras dos 10 primeiros grupos (produto • operação).
- **Amostras**: tabela com Produto, Operação, Recurso, Amostra, Média, Mediana, Mínimo, Máximo, Desvio.

### Como ler a tabela

| Coluna | Em palavras |
|---|---|
| Amostra | Quantas execuções entraram. Poucas = número fraco. |
| Média | Soma dos tempos ÷ amostras. |
| Mediana | O valor do meio: não se deixa levar por um dia muito ruim. |
| Mínimo / Máximo | Melhor e pior tempo por peça. |
| Desvio | Quanto os tempos variam. Perto de zero = processo estável. Com 1 amostra, é zero. |

Exemplo: tempos de 60, 62 e 90 s por peça. Média 70 s, mediana 62 s. O 90 puxou a média; vale investigar o que aconteceu naquela execução.

## Problemas comuns

| Situação | O que fazer |
|---|---|
| "Dados insuficientes" | Sem execuções medidas; aumente o período. |
| Desvio grande | Verificar trocas de operador, material ou setup no meio. |

Veja também: [Tempo padrão × real](topico:74-analises-tempo-padrao-real).
