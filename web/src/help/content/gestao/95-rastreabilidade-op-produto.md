---
titulo: Rastreabilidade - OP / Produto
grupo: Relatórios e rastreabilidade
ordem: 95
rotas: /rastreabilidade/op-produto
---

Tela **Rastreabilidade — OP / Produto**. Você digita uma OP e vê por onde ela passou: operações, máquinas, quantidades, inspeções e a linha do tempo. Frase da tela: "A rastreabilidade mostra por onde a OP passou, com quantidades e eventos."

## Como usar

1. Digite o número no campo **Buscar OP**. A busca roda sozinha cerca de meio segundo depois que você para de digitar.
2. Leia os cartões do topo.
3. Desça para ver operações, inspeção e linha do tempo.

Esta tela **não usa** os filtros globais. O número da OP fica no endereço (`?op=`), então você pode copiar o link. Sem OP aparece "Informe uma OP".

## Cartões

| Cartão | O que significa |
|---|---|
| Situação atual | Status da última operação da lista (a de baixo). "Não disponível" se a OP não tem operações. O detalhe mostra o número da OP. |
| Peças boas | Soma das boas de todas as operações da lista; o detalhe diz quantas operações foram percorridas. |
| Perdas | Refugo + retrabalho somados das operações. O detalhe separa os dois. Fica vermelho se maior que zero. |
| Eventos registrados | Quantidade de eventos na linha do tempo. Mostra também quantos nestings de Corte estão ligados. |

## Inspeção dispensada

Aparece um selo amarelo se a Qualidade dispensou a inspeção: "A inspeção desta OP foi dispensada, sem medição de peças." Se houve mais de uma dispensa, a frase vira "N inspeções desta OP foram dispensadas, sem medição de peças." Colunas: Operação, Recurso, Quantidade, Motivo, Autorizado por, Crachá, Data.

## Operações e produto

Colunas: Operação, Descrição, Produto, Setor, Recurso real, Recurso divergente (traço quando a máquina foi a planejada), Operador (quem iniciou; se não houver, quem finalizou), Boas, Refugo, Retrabalho, Status, Origem ("Apontamento número"). Campo sem dado mostra "Não disponível".

## Nestings de Corte da OP

Só aparece se a OP veio de um plano de corte. Colunas: Tarefa/lote, Programa, Nesting, Máquina, Aproveitamento. Veja [Lote / Material / Nesting](topico:96-rastreabilidade-lote-material-nesting).

## Peças inspecionadas

| Coluna | O que mostra |
|---|---|
| Peça nº | Número da peça inspecionada. |
| Resultado | Aprovada (verde), Retrabalho (amarelo) ou Refugo (vermelho). |
| Operador, Data/hora | Quem inspecionou e quando. |
| Cotas fora do padrão | Quantas medidas ficaram fora. |
| RNC | Número do RNC, se houve. Veja [RNC](topico:62-qualidade-rnc). |
| Cotas (botão Ver cotas / Ocultar cotas) | Abre a tabela Cota, Padrão, Medido, Situação (Conforme ou Não conforme). |

Vazio: "Nenhuma peça inspecionada — Esta OP não tem inspeção registrada pela Qualidade." Ou "Nenhuma cota medida nesta peça". Medidas em [Qualidade — Cotas](topico:60-qualidade-cotas).

## Linha do tempo

O bloco se chama "Linha do tempo da OP (número) — mais recente primeiro". Colunas: Data e hora, Máquina/recurso, OP, Operação, Evento, Status, Operador, Quantidade, Motivo/detalhe, Registro original ("Fonte não disponível" quando não há).

## Quem pode ver

Gestão. Líder e supervisor só veem OPs que passaram pelo próprio setor. Outra OP retorna: "Essa OP não passou pelo seu setor."

## Problemas comuns

- **"Essa OP não passou pelo seu setor."**: seu perfil é restrito ao setor. Peça a quem tem acesso geral.
- **OP não encontrada / tela vazia**: confira o número digitado.
- **"OP é obrigatória para rastreabilidade."**: o campo ficou vazio.
- **Recurso divergente**: máquina real diferente da planejada.

Veja [perfis e acessos](topico:02-perfis-e-acessos).
