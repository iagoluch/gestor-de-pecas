---
titulo: Tela do Destaque
grupo: Destaque
ordem: 30
rotas:
---

**Destaque** é a etapa em que as peças são separadas da chapa depois do corte. Você vê só o que o Corte já liberou.

## Fila de tarefas liberadas

- **Filtrar tarefas liberadas**: digite tarefa, plano ou material. **Limpar filtro** desfaz.
- Cada tarefa é um cartão "Tarefa X" com etiqueta **Corte concluído** ou **Corte parcial**, "N plano(s) pronto(s) para destacar" e "material · espessura mm". Clicar de novo desmarca.
- Dica: "Selecione uma tarefa e um plano liberado pelo Corte."

Vazios: "Nenhuma tarefa liberada pelo Corte" / "Assim que um plano do Laser Ensis for concluído, ele aparece aqui." e "Nenhuma tarefa corresponde ao filtro".

## Tarefa selecionada

Mostra "Tarefa selecionada", "N plano(s) liberado(s)", Material, Espessura e "Tempo em destaque". Abaixo, "Escolha o plano para apontar".

Cada plano é um cartão ("Toque para selecionar" / "Selecionado"). O nome é "Plano X" ou "Nesting N do plano X". Mostra Chapa, Máquina, Peças e "Liberado em". Etiquetas:

| Etiqueta | Significado |
|---|---|
| Aguardando destaque | Pronto para começar. |
| Destaque em execução | Em andamento. |
| Destaque parado | Parado. |
| Destaque concluído | Terminado ("Concluído por X em data"). |

O botão **i** do plano abre "OPs do plano": OP, produto e setor destino ("Destino não informado" quando falta). Vazio: "Nenhuma OP encontrada para este plano". Só aparecem planos já cortados: "Nenhum plano liberado" / "Somente planos concluídos no Laser Ensis aparecem para apontamento."

## Botões

| Botão | Quando |
|---|---|
| **Iniciar** (ou **Retomar produção**, **Iniciar atividade**) | Há plano aguardando ou parado; ou posto parado sem tarefa; ou atividade. |
| **Parada** | Parar o destaque. |
| **Finalizar** (ou **Finalizar atividade**) | Só com plano em execução. |

Aviso: "Posto parado — motivo. Retome para voltar a apontar."

## Passos: destacar um plano

1. Selecione a tarefa e o plano.
2. Clique em **Iniciar**.
3. Ao terminar, clique em **Finalizar**.
4. No popup **Finalizar Destaque**, confira cada OP (marque a caixa; use **Buscar peça ou OP**, **Marcar todas**, **Desmarcar todas**). Enquanto faltar: "N OP(s) ainda não conferida(s)."
5. Passe seu **Crachá do operador**.
6. Clique em **Confirmar fim**. O botão só habilita com todas as OPs conferidas e o crachá.

Atenção: finalizar o Destaque encerra a tarefa inteira no sistema.

## Parar o Destaque

**Parar Destaque**: escolha o motivo, comentário se exigido, **Confirmar parada** (veja [Parada e motivos](topico:06-parada-e-motivos)).

## Histórico

Mostra os últimos 5 eventos. **Ver mais** abre "Histórico do Destaque". Cada evento tem estado (Em execução, Parada, Finalizada, Aguardando), motivo, operador e comentário. Vazio: "Sem eventos registrados" / "O histórico aparece após o primeiro apontamento do Destaque."

## Atividade diária

Popup **Atividade diária**: **Sim** ou **Não**.

Veja também [Corte](topico:20-corte).
