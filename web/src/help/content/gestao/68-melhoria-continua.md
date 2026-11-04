---
titulo: Melhoria Contínua
grupo: Melhoria Contínua
ordem: 68
rotas: /melhoria-continua
---

A tela **Melhoria Contínua** mostra onde a fábrica mais perde no período: paradas, refugo e operações que passaram do tempo padrão. Ela não tem abas e não grava nada. Só reaproveita números das telas de Análises.

Texto da tela: "Onde a fábrica mais perde no período: paradas, refugo e tempo acima do padrão."

## Quem pode ver

Só **Admin** e quem recebeu o nível **Melhoria Contínua**. Os outros veem "Acesso restrito à Melhoria Contínua" e o aviso de que a tela é exclusiva da Melhoria Contínua e da administração.

## Filtros

Usa a barra de filtros do topo (período, setor, recurso e outros). Veja [Filtros globais](topico:04-filtros-globais). Mudou o filtro, as três listas mudam.

## As três listas

Cada lista mostra os **8 maiores** itens, em barras. A barra mais longa é o maior.

| Lista | O que mostra | Origem | Quando vazia |
|---|---|---|---|
| Maiores causas de parada (tempo parado) | Motivos de parada, do que mais tempo parou para o que menos. Cada barra mostra as horas. | Mesma conta de [Paradas](topico:72-analises-paradas). | "Sem paradas no período" |
| Maiores motivos de refugo (N peças no período) | Motivos de refugo, pela quantidade de peças. O título mostra o total de peças refugadas. | Mesma conta de [Qualidade](topico:73-analises-qualidade). | "Sem refugo no período" |
| Operações que passaram do tempo padrão (mais acima primeiro) | Só operações em que o tempo real passou do padrão. Linha: "OP · operação · produto". Detalhe: "+Xh" (horas acima). | Mesma conta de [Tempo padrão × real](topico:74-analises-tempo-padrao-real). | "Nenhuma operação acima do padrão" |

Como ler: se o motivo "Falta de material" lidera as paradas, o primeiro passo é olhar o abastecimento. Se uma operação aparece sempre na terceira lista, vale revisar o tempo padrão ou o processo.

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| Acesso restrito à Melhoria Contínua | Seu nível não tem acesso. Peça ao admin o nível Melhoria Contínua. |
| Listas vazias com período curto | Aumente o período (por exemplo, 30 dias). |
| Erro ao carregar | Clique em **Tentar novamente**. |

Os números aqui são os mesmos das Análises. Se algo parecer estranho, confira lá, onde os valores são clicáveis e mostram a conta.
