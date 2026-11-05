---
titulo: Consulta Operacional - Recursos
grupo: Consulta operacional
ordem: 31
rotas: /consulta-operacional/recursos
---

Tela **Consulta Operacional — Recursos**. Frase de apresentação: "Estado, OP, operador e duração por recurso físico no dia corrente."

É a [Visão Geral](topico:30-consulta-visao-geral) em formato de tabela, com filtro por setor.

## Filtros

- O período é fixo: **dia corrente**. Em vez do período aparece "Situação do dia corrente" (veja [Filtros globais](topico:04-filtros-globais)).
- Estão disponíveis **Setor** e **Mais filtros** (Recurso, OP, Operação, Produto, Operador). Use Aplicar e Limpar.
- Se você chegou por um link do Início com `?setor=...`, o setor já vem aplicado no filtro e o texto some do endereço.

A tela carrega até 200 recursos por vez.

## Cartões do topo

| Cartão | O que mostra | Observação |
|---|---|---|
| Recursos no filtro | Total de recursos que passam pelo filtro. | Vem do total do servidor. |
| Em produção agora | Número de recursos em produção. | Clicável. Se a lista tem menos que o total: "Lista com N de M recursos do filtro." |
| Parados | Número de recursos em parada. | Clicável. Detalhe "Verifique o motivo na tabela" ou "Nenhuma parada aberta". |
| Maior parada aberta | Maior duração de parada, em HH:MM:SS. | Detalhe "Recurso — motivo" ou "Atualizado em" com a data. |

## Tabela "Recursos"

| Coluna | O que mostra |
|---|---|
| Recurso | Nome do recurso. |
| Setor | Setor do recurso. |
| Estado | Etiqueta colorida (cores na [Visão Geral](topico:30-consulta-visao-geral)). |
| OP | Número da OP. Clique para abrir a rastreabilidade. Usa a primeira OP ativa do recurso. |
| Produto | Produto da OP. |
| Operador | Operador que iniciou o apontamento. |
| Início | Quando o estado atual começou (dd/mm/aaaa hh:mm). |
| Duração | Tempo no estado, em HH:MM:SS. |
| Motivo | Motivo do estado. "Não disponível" se vazio. |

Se um recurso tem mais de uma OP ativa, a tabela mostra só a primeira. As demais contam no total de OPs em execução da Visão Geral.

## Fila de prioridades

Abaixo da tabela aparece o painel **Fila de prioridades** quando:

1. o filtro Setor está em um setor que pertence a uma área, e
2. sua conta pode ordenar a fila dessa área.

Como funciona está em [Áreas](topico:35-areas-tela-generica).

## Quem vê

Qualquer conta da gestão. Líder e supervisor presos a um setor veem só o próprio setor (o servidor aplica o filtro).

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| Tabela vazia | Nenhum recurso passa pelo filtro. | Clique em Limpar. |
| "Lista com N de M recursos do filtro." | O filtro tem mais de 200 recursos. | Filtre por setor para ver todos. |
| Estado "desconhecido" | Sem estado registrado para o recurso. | Confirmar com a liderança. |
