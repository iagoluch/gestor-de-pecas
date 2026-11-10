---
titulo: Auditoria - Eventos de Produção
grupo: Auditoria
ordem: 90
rotas: /auditoria/eventos-producao, /auditoria/apontamentos
---

Tela **Auditoria — Eventos de Produção**. Mostra o trabalho executado: OP, produto, operação, recurso, colaborador, início e fim, atividade (produção, setup ou retrabalho), tempo real, tempo padrão por peça e as quantidades boas, refugo e retrabalho.

Ela só **mostra**. Nada aqui altera o histórico.

## Como as quantidades entram

As peças vêm do registro de quantidades e são ligadas pela OP e pela operação. Cada quantidade entra **uma vez só**, na linha de produção (nunca no setup). Por isso o total não duplica.

Se uma quantidade não encontra o apontamento correspondente, ela aparece numa linha própria com o selo **Quantidade sem evento**, para você investigar.

## Corte

O Corte aparece pela **Tarefa** e pelo **Plano** cortado, sem OP, como no resto do sistema.

## Diferença para Eventos de Status

O status explica o uso do tempo do recurso. Esta tela explica o trabalho feito nesse tempo.
