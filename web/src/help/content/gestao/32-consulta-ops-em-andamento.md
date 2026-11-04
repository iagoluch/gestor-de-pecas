---
titulo: Consulta Operacional - OPs em andamento
grupo: Consulta operacional
ordem: 32
rotas: /consulta-operacional/ops-em-andamento
---

Tela **Consulta Operacional — OPs em andamento**. Frase de apresentação: "Execuções do dia corrente, mantendo quantidade boa, refugo e retrabalho separados."

Ela responde: **quais OPs estão rodando hoje e como estão as quantidades?**

## Filtros

- Período fixo: dia corrente.
- Disponíveis: Setor e Mais filtros (Recurso, OP, Operação, Produto, Operador). Veja [Filtros globais](topico:04-filtros-globais).

## Quais OPs entram

Só OPs com status **Aguardando, Em processo, Parada, Setup ou Retrabalho**. OP finalizada não aparece aqui. A tela carrega até 200 linhas.

## Cartões do topo

| Cartão | O que mostra | Como é calculado |
|---|---|---|
| OPs em andamento | Total de OPs no filtro. | Total do servidor. |
| Peças boas hoje | Soma das peças boas. Detalhe: "Somente peças boas". | Soma das boas das linhas carregadas. Clicável. |
| Refugo | Soma do refugo. Detalhe: "X% da produção". | Refugo dividido por (boas + refugo), vezes 100. O percentual só aparece se houver boas. Clicável. |
| OPs paradas | Quantidade de linhas com status Parada. Detalhe: "Verifique o motivo na tabela" ou "Nenhuma OP parada". | Clicável: lista cada OP parada. Se a lista foi cortada: "Contagem das N OPs carregadas; o filtro tem M no total." |

Retrabalho não entra em "peças boas" nem reduz saldo. Ele aparece separado na tabela.

## Tabela "Ordens em execução"

| Coluna | O que mostra |
|---|---|
| OP | Número da OP. Clique para abrir a rastreabilidade. |
| Produto | Produto da OP. |
| Operação | Operação em andamento. |
| Recurso | Recurso real onde a OP está. |
| Planejado | Quantidade planejada. |
| Boas | Peças boas apontadas. |
| Refugo | Peças refugadas. |
| Retrabalho | Peças em retrabalho. |
| Status | Etiqueta colorida (verde, vermelho, amarelo, azul, cinza). Parada fica vermelha, Setup amarela, Em processo azul. |
| Início | Quando a execução real começou. |

## Quem vê

Qualquer conta da gestão. Líder e supervisor veem só o próprio setor.

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| Tabela vazia | Nenhuma OP ativa no filtro. | Clique em Limpar. |
| "Contagem das N OPs carregadas..." | Mais de 200 OPs no filtro. | Filtre por setor ou recurso. |
| Percentual de refugo ausente | Não há peças boas ainda. | Normal no começo da produção. |

## Veja também

- [Produção — Execução das OPs](topico:46-producao-execucao-das-ops) (OPs de qualquer período, com saldo).
- [Consulta de OP](topico:45-producao-consulta-de-op) (roteiro completo de uma OP).
