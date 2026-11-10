---
titulo: Auditoria analítica
grupo: Auditoria
ordem: 88
rotas: /auditoria/analitica
---

Tela **Auditoria analítica**. Uma tela só, com um seletor de **tipo de relatório**. Por enquanto há dois tipos:

- **01 — Eventos de status**: em que condição cada recurso esteve e por quanto tempo.
- **02 — Eventos de produção**: o que foi executado, com tempo real e quantidades.

Ela só **mostra**. Nada aqui altera o histórico.

## Filtros

Período, setor, recurso, OP, colaborador, produto e operação ficam na barra de cima e **continuam valendo quando você troca o tipo**. Se algum filtro não vale no tipo escolhido, a tela avisa que ele foi ignorado (ele não é apagado).

O tipo 01 tem filtros próprios: **Status**, **Classificação** e **Situação** (só em aberto).

## Referência (as_of) e período

Cada consulta mostra a **Referência**: o instante até onde o tempo foi contado.

Entra todo evento que toca o período, mesmo que tenha começado antes ou termine depois. O tempo contado é só a parte dentro do período. Evento ainda aberto aparece sem fim e conta até a Referência.

## O que a tela pode dizer

- **Sem registros**: nenhum evento no período e nos filtros.
- **Soma zero**: há registros, mas a medida principal (duração ou produção) é zero.
- **Fonte indisponível**: a fonte do relatório não existe nesta instalação. Não quer dizer zero.
- **Erro**: a consulta falhou; use "Tentar de novo".

## Detalhe e exportação

Clique em **Ver** numa linha para abrir todos os campos do registro.

**Exportar CSV** baixa todas as linhas (não só a página) e todos os campos, com os mesmos filtros da tela.
