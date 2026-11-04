---
titulo: Rastreabilidade - Lote / Material / Nesting
grupo: Relatórios e rastreabilidade
ordem: 96
rotas: /rastreabilidade/lote-material-nesting
---

Tela **Rastreabilidade — Lote / Material / Nesting**. Lista as chapas cortadas (nestings) com material, tempo, aproveitamento e as OPs ligadas. Serve para saber de qual tarefa e de qual chapa saiu uma peça. Veja o vocabulário do Corte em [Dobra e Corte](topico:36-area-dobra-e-corte).

## Filtros

Dos [filtros globais](topico:04-filtros-globais) só vale o **Recurso** (período e máquina). Setor, OP, operação, produto e operador não se aplicam à fonte do Corte.

O campo **Buscar tarefa, material ou nesting** procura em tarefa, programa, nesting, máquina, material e status.

## Cartões

| Cartão | O que significa |
|---|---|
| Nestings no filtro | Quantos nestings entram no filtro. |
| Tempo previsto | Soma do tempo previsto. |
| Tempo realizado | Soma do tempo realizado. |
| Desvio do previsto | (realizado − previsto) ÷ previsto × 100. Vermelho se o realizado passou do previsto. "Sem previsto no filtro" se o previsto é zero. |

As somas são feitas sobre **todo** o filtro, não só sobre a página. Os valores são clicáveis para ver o cálculo, mas só enquanto não há busca ativa.

## Aproveitamento da chapa

- **Aproveitamento médio**: média simples entre os nestings que têm dado. "Sem nesting com dado no filtro" se nenhum tem.
- **Nestings com dado**: "de N no filtro".
- **Nestings sem dado**: "Não entram na média".

Regra da tela: aproveitamento = (1 − fração de sucata) × 100, por nesting. A área total da chapa não é gravada.

## Tabela "Lotes, materiais e nestings"

| Coluna | O que mostra |
|---|---|
| Tarefa/lote | Tarefa do Corte. |
| Programa, Nesting | Identificação do programa e da chapa. |
| Máquina | Máquina de corte. |
| Material, Espessura (mm) | Material e espessura. |
| Tempo previsto | Tempo planejado. |
| Tempo total | Tempo realizado total do nesting. |
| Tempo no período | Parte do tempo que caiu dentro do período filtrado. É outra grandeza, não some com o total. |
| Desvio | Diferença contra o previsto. |
| Aproveitamento | Percentual da chapa aproveitado. |
| Operador | Quem cortou. |
| OPs relacionadas | Links para a [rastreabilidade da OP](topico:95-rastreabilidade-op-produto). |
| Status | Situação do nesting. |

## Aproveitamento por tarefa

Tarefa/lote, Nestings, Com dado, Aproveitamento médio.

## Quem pode ver

Gestão. Veja [perfis e acessos](topico:02-perfis-e-acessos). Páginas de 200 linhas.

## Problemas comuns

- **Aproveitamento vazio**: o nesting não trouxe o dado de sucata. Não entra na média.
- **Tempo no período menor que total**: normal; o nesting atravessa o período.
- **Filtro de setor/operador sem efeito**: não se aplicam a esta tela.
