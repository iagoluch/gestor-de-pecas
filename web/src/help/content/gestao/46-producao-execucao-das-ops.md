---
titulo: Produção - Execução das OPs
grupo: Produção
ordem: 46
rotas: /producao/execucao
---

Tela **Produção — Execução das OPs**. Frase de apresentação: "Plano corporativo em leitura e execução real do Gestor, sem permitir edição do planejamento."

Ela responde: **quanto do plano já foi atendido e quanto falta?** É só leitura. Nada se edita aqui.

## Filtros e busca

- Barra de filtros global: período, Setor e Mais filtros (veja [Filtros globais](topico:04-filtros-globais)). O período é o que você escolher, não só hoje.
- Campo de busca no topo: "Buscar OP, produto ou recurso". Procura por OP, produto, descrição, operação e recurso (real ou planejado). A busca espera você parar de digitar.

A tela carrega até 200 linhas.

## Cartões do topo

Todos podem ser clicados para ver de onde vem o número (soma por OP). Se a lista foi cortada: "Soma das N linhas carregadas; o filtro tem M no total."

| Cartão | O que mostra | Como é calculado |
|---|---|---|
| Ordens no filtro | Total de linhas no filtro. | Total do servidor. |
| Quantidade planejada | Detalhe: "Somatório das OPs do filtro". | Soma da quantidade planejada. |
| Peças boas produzidas | Detalhe: "X% do planejado (só boas)". | Soma das boas. Percentual = boas ÷ planejada × 100. |
| Saldo a produzir | Detalhe: "N atendidas (boas + refugo); retrabalho não reduz saldo". | Soma dos saldos das linhas. Amarelo se maior que zero. Verde se zero. |

## Regras dos números

- **Atendida** = boas + refugo.
- **Saldo** = planejada − boas − refugo, nunca abaixo de zero.
- **% atendida** = atendida ÷ planejada × 100, limitada entre 0 e 100. Sem quantidade planejada, não há percentual.
- **Planejada** = a quantidade do PCP. Se não houver, usa a quantidade da OP.
- **Retrabalho** não reduz saldo.

## Tabela "Ordens de Produção"

As colunas podem ser ordenadas. A coluna OP fica fixa à esquerda.

| Coluna | O que mostra |
|---|---|
| OP | Número da OP. Clique para abrir a rastreabilidade. |
| Status | Etiqueta colorida. |
| Produto | Código do produto. Passe o mouse para ver a descrição. |
| Operação | "sequência · operação". |
| Recurso | Recurso real. Se não houver, o planejado. |
| Prioridade | Prioridade da OP. |
| Planejada | Quantidade planejada. |
| Boa | Peças boas. |
| Refugo | Peças refugadas. |
| Atendida | Boas + refugo. |
| Saldo | O que falta. |
| % atendida | Percentual atendido. |
| Próxima operação | A próxima operação do roteiro. |

## Quem vê

Qualquer conta da gestão. Líder e supervisor veem só o próprio setor.

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| Tabela vazia | Nada no período e filtros escolhidos. | Amplie o período ou clique em Limpar. |
| "Soma das N linhas carregadas..." | Há mais de 200 linhas no filtro. | Restrinja o filtro para ver o total exato. |
| Saldo zero com OP incompleta | Refugo conta como atendido. | Veja a coluna Refugo. |

## Veja também

- [Planejado × Realizado](topico:48-producao-planejado-realizado).
- [Produção realizada](topico:47-producao-realizada).
- [Consulta de OP](topico:45-producao-consulta-de-op).
