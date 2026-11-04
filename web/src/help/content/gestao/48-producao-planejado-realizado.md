---
titulo: Produção - Planejado × Realizado
grupo: Produção
ordem: 48
rotas: /producao/planejado-realizado
---

Tela **Produção — Planejado × Realizado**. Frase de apresentação: "Comparação somente leitura entre o plano corporativo e a execução registrada."

Ela responde: **o que o plano pedia e o que a fábrica entregou?**

## Filtros

Barra de filtros global: período, Setor e Mais filtros (veja [Filtros globais](topico:04-filtros-globais)). A tela carrega até 200 comparações.

## Cartões do topo

| Cartão | O que mostra | Como é calculado |
|---|---|---|
| Quantidade planejada | Total do plano. Detalhe: "N comparações no filtro". | Soma do plano. |
| Realizado (boas) | Total de peças boas. | Soma das boas. |
| Atendimento | Percentual atendido. Detalhe: "N boas + refugo · saldo M". | (boas + refugo) ÷ planejada × 100. Se não há plano: "Sem plano no filtro". |
| Perdas no período | Refugo + retrabalho. Detalhe: "N refugo · M retrabalho". | Vermelho se maior que zero. |

Atendimento conta refugo como atendido. Retrabalho fica fora e não reduz saldo.

## Tabela "Plano × Real por OP/operação"

| Coluna | O que mostra |
|---|---|
| OP | Número da OP. Clique para abrir a rastreabilidade. |
| Operação | A operação. |
| Produto | O produto. |
| Recurso planejado | Onde o plano previa fazer. |
| Recurso real | Onde foi feito. |
| Quantidade plano | Quantidade planejada. |
| Quantidade boa | Peças boas. |
| Refugo | Peças refugadas. |
| Retrabalho | Peças em retrabalho. |
| Atendida | Boas + refugo. |
| Saldo | O que falta. |
| Início planejado | Data prevista de início. |
| Início real | Data real de início. |

Recurso real diferente do planejado indica que a produção foi feita em outro posto.

## Quem vê

Qualquer conta da gestão. Líder e supervisor veem só o próprio setor.

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| Sem plano no filtro | Não há quantidade planejada nos filtros escolhidos. | Amplie o período ou limpe os filtros. |
| Tabela vazia | Nenhuma comparação no filtro. | Clique em Limpar. |
| Início real vazio | A operação ainda não começou. | Normal. |

## Veja também

- [Execução das OPs](topico:46-producao-execucao-das-ops).
- [Produção realizada](topico:47-producao-realizada).
