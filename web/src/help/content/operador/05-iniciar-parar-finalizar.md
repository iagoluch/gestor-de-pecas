---
titulo: Iniciar, parar e finalizar
grupo: Tela do posto
ordem: 5
rotas:
---

Os botões ficam na barra "Ações operacionais". Botão apagado significa que, agora, o sistema não permite aquela ação. Muitas vezes o texto que aparece ao passar o mouse explica o motivo.

## Os botões

| Botão | Para que serve | Quando fica ativo |
|---|---|---|
| **Iniciar** | Começa a produção da etapa selecionada. | Etapa selecionável; OP fora de Em processo, Setup e Retrabalho; sem outra OP em Setup/Retrabalho no posto; sem bloqueio de primeira peça. |
| **Retomar produção** | É o mesmo botão Iniciar, com outro nome, quando o posto está em Parada ou Setup. | Posto em Parada ou Setup. |
| **Iniciar retrabalho** | Aparece no lugar de Iniciar quando a OP voltou para retrabalho. | OP em retorno de retrabalho. |
| **Iniciar atividade** | Aparece quando não há OP carregada. Inicia atividade sem OP. | Sem OP. |
| **Parada** (ou **Parada do posto**, se não há OP ativa) | Registra uma parada. | Veja [Parada e motivos](topico:06-parada-e-motivos). |
| **Finalizar** | Encerra a produção e informa as quantidades. | Veja abaixo. |
| **Setup** | Registra a preparação da máquina. Só existe em setores com setup. | Veja [Setup e primeira peça](topico:07-setup-e-primeira-peca). |
| **Retrabalho** / **Finalizar Ret.** | Começa ou encerra retrabalho. | Veja [Retrabalho](topico:08-retrabalho). |

## Iniciar uma operação

1. [Carregue a OP](topico:04-carregar-op-e-roteiro).
2. Selecione a etapa no roteiro.
3. Clique em **Iniciar**.
4. A barra de estado passa para **Produzindo** e o cronômetro começa.

O que o botão faz depende do estado: se a OP estava Parada, ele retoma. Se estava em Setup, volta à produção. Se voltou do retrabalho, inicia o retrabalho. Nos demais casos é o início normal.

## Exceções que pedem crachá

Se você apontar algo que foge do roteiro, abre **Autorizar exceção operacional**. Ele mostra uma destas linhas:

- "Etapa atual da OP: x." e "Etapa anterior pendente: ..."
- "Recurso do roteiro: COD (nome)"
- "A execução diverge do roteiro e exige confirmação."

Passos:

1. Peça a quem autoriza para passar o crachá em **Crachá autorizado**.
2. Clique em **Autorizar e continuar**.

**Cancelar** desiste.

## Finalizar

1. Clique em **Finalizar**. Abre o popup de quantidades: veja [Finalizar e informar quantidades](topico:09-finalizar-quantidades-e-crachas).
2. Se o botão estiver apagado, passe o mouse sobre ele:
   - "Encerre o retrabalho primeiro (Finalizar Ret.)." Termine o retrabalho antes.
   - Mensagem de primeira peça, por exemplo "Aponte o Setup desta operação para conferir a primeira peça antes de finalizar." Veja [Setup e primeira peça](topico:07-setup-e-primeira-peca).

## Atividade sem OP

1. Clique em **Iniciar atividade**.
2. Abre "Atividade sem OP": "Iniciar uma atividade sem OP neste posto?" Responda **Sim** ou **Não**.
3. Para encerrar, clique em **Finalizar** (o botão aparece como Finalizar atividade) e responda "Finalizar a atividade sem OP em andamento?"

## Mais de uma OP no mesmo posto

Alguns postos aceitam produzir várias OPs ao mesmo tempo. Cada uma tem seu card em Produção. Nos postos que não aceitam, o sistema recusa iniciar outra OP enquanto houver uma em andamento (Setup ou Retrabalho) e mostra a mensagem do quadro abaixo. Qual posto aceita é regra de cadastro: confirmar com a liderança.

## Problemas comuns

| Mensagem ou situação | O que fazer |
|---|---|
| "Esta OP já foi apontada em outra estação." | A OP está em outro posto. Fale com a liderança. |
| "Há setup ou retrabalho em andamento neste posto. Finalize-o antes de iniciar outra OP." | Finalize o Setup ou o Retrabalho que está aberto. |
| "Recurso parado — {motivo}. Retome para voltar a apontar." | Clique em **Retomar produção**. |
| **Iniciar** apagado | Etapa não selecionada, OP já em andamento, ou outro Setup/Retrabalho aberto. |
