---
titulo: Análises - Paradas e Setup
grupo: Análises
ordem: 72
rotas: /analises/paradas
---

A tela **Análises — Paradas & Setup** mostra quanto tempo as máquinas ficaram paradas ou em setup (preparação), e por quê. Tem dois botões no alto: **Paradas** e **Setup**. A tela e os cartões mudam conforme o botão.

Usa a barra de filtros do topo. Veja [Filtros globais](topico:04-filtros-globais).

- Paradas: "Tempo, frequência, classificação e motivo das paradas físicas."
- Setup: "Tempo de setup produtivo, separado da produção e sem penalizar Disponibilidade ou Performance."

## Cartões

| Cartão | Aparece em | Significado |
|---|---|---|
| Parada não planejada | Paradas | Tempo parado fora do plano. Detalhe: média por recurso. |
| Parada planejada | Paradas | Tempo parado previsto. Detalhe: média por recurso. |
| Tempo total de setup | Setup | Total de horas em setup. Detalhe: média por recurso. |
| Ocorrências | Ambos | Quantas paradas (ou setups). Detalhe: "Média de X por ocorrência". Clicável: abre a lista que forma o número. |
| Recurso mais parado / Recurso com mais setup | Ambos | Máquina com mais horas (o detalhe mostra as horas). "Não determinado" se não houver registros. |
| Maior parada / Setup mais longo | Ambos | O motivo que mais tempo somou: mostra as horas e, embaixo, o nome do motivo. "Nenhuma" se vazio. |

Os valores de horas (parada não planejada, parada planejada e total de setup) são clicáveis e abrem a conta aberta. A média por recurso só aparece com 2 ou mais recursos.

## Pareto por motivo

"Pareto por motivo" (Paradas) ou "Tempo por tipo de setup" (Setup): barras com os 10 maiores motivos, do que mais tempo tirou para o que menos. Foque nos primeiros: poucos motivos costumam explicar a maior parte do tempo perdido.

## Tabela Ocorrências

| Coluna | Significado |
|---|---|
| Recurso | Máquina ou posto. |
| Setor | Setor do recurso. |
| Motivo | Motivo informado. |
| Classificação | Paradas: "Programada" ou "Não programada". Setup: o tipo do setup (ou "Setup" se não houver tipo). |
| Início | Data e hora de início. |
| Tempo | Duração. |
| OP | OP ligada à ocorrência; clique para abrir a OP em Rastreabilidade. "—" se não houver. |

Em Paradas, pode aparecer uma linha "diferença: ± horas, motivo: ..." quando o total difere da soma da lista; o motivo explica.

## Problemas comuns

| Situação | O que fazer |
|---|---|
| Lista vazia | Aumente o período ou limpe filtros. |
| Motivo "Não informado" | A parada foi lançada sem motivo; orientar o operador. |
| Erro ao carregar | Clique em **Tentar novamente**. |

Veja também: [Confiabilidade](topico:77-analises-confiabilidade) e [Análises — OEE](topico:70-analises-oee).
