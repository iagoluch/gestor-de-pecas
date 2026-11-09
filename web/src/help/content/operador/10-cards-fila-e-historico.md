---
titulo: Cards, fila e histórico
grupo: Tela do posto
ordem: 10
rotas:
---

Abaixo dos botões há três seções de cards.

| Seção | O que mostra |
|---|---|
| **Produção** | OPs ativas no posto: Em processo, Parada, Setup ou Retrabalho. |
| **Fila de Ordem** | OPs esperando a vez neste posto. |
| **Histórico** | Só as OPs **concluídas** (Finalizado), as mais recentes primeiro (até 100 de cada vez). OP finalizada em parte volta para a Fila. |

Cada seção mostra **2 cards**, um contador e o botão **Ver mais**.

## Ver mais

Abre um popup com a lista completa da seção. No Histórico, quando existem mais registros do que cabem, aparece: "Exibindo os 100 registros mais recentes. Use os filtros dos relatórios para consultas históricas maiores."

## Seção vazia

| Seção | Mensagem |
|---|---|
| Produção | "Nenhuma OP em produção" |
| Fila de Ordem | "Fila vazia" |
| Histórico | "Sem apontamentos recentes" (ou "Carregando histórico") |
| No popup Ver mais | "Nenhum item em produção", "Nenhum item em fila de ordem" ou "Nenhum item em histórico" |

## O que tem em cada card

| Campo | Significado |
|---|---|
| **OP: x** | Código da OP. Uma marca de visto indica a OP selecionada. |
| Etiqueta de status | Ex.: Em processo, Parada, Aguardando (padrão quando não há status). Veja [Estados e cores](topico:90-estados-e-cores). |
| Etiqueta **Parcial X/Y** (amarela) | A OP já teve X peças apontadas de Y e ainda tem saldo. |
| Início | Hora em que **esta** OP começou. Com várias OPs no posto, cada uma tem a sua; a faixa do topo mostra desde quando o posto está nesse estado. |
| Operação | A etapa. |
| Produto e Descrição | A peça. |
| Quantidade | O que a OP pede. |
| Boas | Peças boas já registradas. |
| Refugo | Refugo já registrado. |
| Tempo | Tempo acumulado. |
| Última atualização | Hora do último registro. |
| Motivo, Desde, Tempo parado | Só em OP parada. O tempo parado aparece em alerta. |

## Clicar no card

Carrega aquela OP e etapa na tela (como digitar o código). Não registra nada.

## Problemas comuns

- **A OP não está em nenhuma seção**: ela pode estar em outro posto. Digite o código em [Carregar a OP](topico:04-carregar-op-e-roteiro).
- **Números parecem velhos**: veja o aviso "Atualização temporariamente indisponível" em [A tela do posto](topico:03-tela-do-posto).
