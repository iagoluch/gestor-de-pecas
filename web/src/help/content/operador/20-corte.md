---
titulo: Tela do Corte
grupo: Corte
ordem: 20
rotas:
---

No Corte você não aponta por OP. Você aponta por **tarefa**, **plano** e **nesting**.

## Palavras do Corte

| Palavra | O que é |
|---|---|
| **Tarefa** | O trabalho de corte programado. Só identifica o serviço. |
| **Plano** | Uma chapa com as OPs que serão cortadas nela. |
| **Nesting** | Cada repetição da mesma chapa. |
| **Chapa** | A folha de material cortada. |

A ordem é: Tarefa, depois Plano, depois OPs, depois Produtos. O Corte conta pelo plano cortado, não por OP.

## Barra de estado e filtro

- A barra de estado mostra o que o posto faz. Sem nada em andamento, aparece "Sem apontamento".
- **Filtrar a fila**: digite tarefa, programa, material ou chapa. **Limpar filtro** desfaz.
- **Atualizar tarefas** busca novas tarefas. Mostra "Atualizando...". Resultado: "Atualizado às HH:MM" com a mensagem ou "nenhuma tarefa nova". Se falhar: "Não foi possível atualizar as tarefas. Exibindo a última fila sincronizada."
- **Histórico** abre os cortes já finalizados.
- Linha "Última sincronização: ...". Dica padrão: "Fila automática — novas tarefas aparecem sozinhas."

## Cards de tarefa

Cada tarefa é um card, recolhido por padrão (clique no ▶ para abrir, ▼ para fechar).

| Campo | Significado |
|---|---|
| Tarefa (código) e etiqueta | Aguardando, Em processo ou Finalizado. |
| Material, Espessura | O que será cortado. |
| Planos, Chapas, Quantidade | Tamanho do trabalho. |
| Situação | Ex.: "N cortada(s) · M aguardando". |
| Tempo previsto, Tempo realizado | Planejado e já gasto. |
| Em execução | "Plano i/n" ou "Nesting i/n". |

Dentro da tarefa, cada **plano** (fechado por padrão) mostra: programa, "X de Y chapas", estado (ex.: AGUARDANDO CORTE, EM CORTE) e, ao abrir: Chapas, Repetição, Chapa, Tempo previsto, lista de OPs (OP, Produto, Qtd) e tabela de chapas (#, Chapa, Repetição, Status, Previsto, Realizado). Outros estados de plano: confirmar com a liderança.

Mensagens: "Nenhuma OP vinculada a este plano.", "Nenhum plano publicado para esta tarefa.", "OPs sem plano identificado: ..."

## Botões

| Botão | Quando aparece e o que faz |
|---|---|
| **Iniciar corte** | No plano, se a tarefa está Aguardando e há chapa aguardando. Começa o corte. |
| **Finalizar nesting** ou **Finalizar plano** | Encerra a chapa em corte. Aparece como "nesting" quando o plano tem repetição. O sistema já inicia o próximo, se houver. |
| **Finalizar só este plano** | Aparece se há nestings aguardando. Encerra só o atual e deixa o recurso livre. |
| **Registrar parada** | Se o posto não está parado. |
| **Retomar corte** | Se o posto está parado. |
| **Iniciar atividade** / **Finalizar atividade** | Atividade sem plano. "Iniciar atividade" aparece sem plano em processo e sem parada. |

## Passos: cortar um plano

1. Abra a tarefa e o plano.
2. Clique em **Iniciar corte**.
3. Ao terminar, clique em **Finalizar nesting** (ou **Finalizar plano**).

## Parada do Corte

1. Clique em **Registrar parada**. Abre **Parada do Corte**.
2. Busque e escolha o motivo, preencha o comentário se obrigatório (mesmos campos de [Parada e motivos](topico:06-parada-e-motivos)).
3. Clique em **Confirmar parada**.
4. Para voltar, clique em **Retomar corte**. Enquanto parado: "Recurso parado — motivo. Retome antes de finalizar."

## Atividade diária

Popup **Atividade diária**: "Iniciar" ou "Finalizar", com **Sim** e **Não**.

## Histórico do Corte

Tabela com: Tarefa, Programa/plano, Chapa/repetição, Máquina, OPs, Qtd., Publicado SigmaNEST, Início, Fim, Realizado e Estado final. Vazio: "Nenhum corte finalizado neste recurso".

## Vazios e problemas comuns

| Mensagem | Significado |
|---|---|
| "Nenhuma tarefa corresponde ao filtro" / "Limpe o filtro para ver toda a fila do recurso." | O filtro escondeu tudo. Clique em **Limpar filtro**. |
| "Nenhum plano na fila" / "Assim que uma tarefa entrar no planejamento, ela aparece aqui automaticamente." | Não há trabalho. Clique em **Atualizar tarefas**. |
| "Carregando fila do Corte…" | Aguarde. |

Para o que acontece depois do corte, veja [Destaque](topico:30-destaque).
