---
titulo: Auditoria - Apontamentos
grupo: Auditoria
ordem: 90
rotas: /auditoria/apontamentos
---

Tela **Auditoria — Apontamentos**. Mostra cada registro feito no chão de fábrica, para você conferir. Frase da tela: "Registros operacionais e referências de origem para conferência."

Ela só **mostra**. Nada aqui altera o histórico.

## Para que serve

Use quando alguém pergunta "quem apontou isso?", "em qual máquina?" ou "essa OP foi mesmo finalizada?".

## Filtros

Usa os [filtros globais](topico:04-filtros-globais) do topo (período, setor, recurso, OP, operação, produto, operador). A tela carrega até **200 registros** por vez.

## Cartões do topo

O cartão "Apontamentos" mostra o total do período, vindo do servidor. Os outros três contam apenas as linhas carregadas (até 200).

| Cartão | O que significa |
|---|---|
| Apontamentos | Total de registros no período. |
| Finalizados | Quantos já terminaram (status Finalizado). O detalhe diz "N ainda em aberto": é todo registro carregado que não está finalizado. |
| Recursos envolvidos | Quantas máquinas/postos diferentes aparecem nas linhas carregadas. |
| Operadores envolvidos | Quantas pessoas diferentes iniciaram registros nas linhas carregadas ("Quem registrou no período"). |

## Tabela

O bloco se chama "Apontamentos do período".

| Coluna | O que mostra |
|---|---|
| ID | Número do apontamento. |
| OP | Número da OP. Clique para abrir a [rastreabilidade](topico:95-rastreabilidade-op-produto) dela. |
| Operação | Operação apontada. |
| Setor | Setor do posto. |
| Recurso | Máquina/posto onde foi apontado. |
| Recurso divergente | Selo "planejado × apontado" quando a OP foi feita em máquina diferente da planejada. Traço (—) se não houve diferença. |
| Operador | Quem iniciou; se não houver, quem finalizou; senão "—". |
| Status | Situação do registro (em processo, finalizado, parada etc.). |
| Boas, Refugo, Retrabalho | Quantidades registradas. |
| Início, Fim | Data e hora. Fim vazio = ainda aberto. |

Os dados vêm dos apontamentos operacionais e dos eventos do operador.

## Quem pode ver

Somente a gestão. Líder e supervisor veem só o próprio setor. Veja [perfis e acessos](topico:02-perfis-e-acessos).

## Problemas comuns

- **"Sem registros"** ("Nenhum registro encontrado para o período.") no lugar da tabela: não há apontamentos no período/filtro. Amplie o período.
- **Cartões não batem com o total real**: a tela carrega no máximo 200 linhas. Reduza o período.
- **Recurso divergente aparece**: a OP rodou em máquina diferente da planejada. Confirme com o líder do setor se foi troca autorizada.
