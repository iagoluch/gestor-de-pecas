---
titulo: Iniciar, parar e finalizar
grupo: Tela do posto
ordem: 5
rotas:
---

Os botões ficam na barra "Ações operacionais". Botão apagado significa que, agora, o sistema não permite aquela ação. Muitas vezes o texto que aparece ao passar o mouse explica o motivo.

## Os botões

Na tela, a ordem é: Iniciar, Setup, Parada, Retrabalho e Finalizar. Em setor sem Setup, esse botão não aparece e os outros mantêm a ordem.

| Botão | Para que serve | Quando fica ativo |
|---|---|---|
| **Iniciar** | Começa a produção da etapa selecionada. | Etapa selecionável; OP fora de Em processo, Setup e Retrabalho; sem outra OP em Setup/Retrabalho no posto; sem primeira peça reprovada esperando o responsável. |
| **Retomar produção** | É o mesmo botão Iniciar, com outro nome, quando a OP está em Parada. | OP parada. |
| **Iniciar retrabalho** | Aparece no lugar de Iniciar quando a OP voltou para retrabalho. | OP em retorno de retrabalho. |
| **Iniciar** (sem OP) | Aparece quando não há OP carregada. Inicia atividade sem OP. | Sem OP. |
| **Setup** | Registra a preparação da máquina. Só existe em setores com setup. | Veja [Setup e primeira peça](topico:07-setup-e-primeira-peca). |
| **Parada** | Registra uma parada. | Veja [Parada e motivos](topico:06-parada-e-motivos). |
| **Retrabalho** / **Finalizar Ret.** | Começa ou encerra retrabalho. | Veja [Retrabalho](topico:08-retrabalho). |
| **Finalizar** | Encerra a produção e informa as quantidades. | Veja abaixo. |

## Iniciar uma operação

1. [Carregue a OP](topico:04-carregar-op-e-roteiro).
2. Selecione a etapa no roteiro.
3. Clique em **Iniciar**.
4. A barra de estado passa para **Produzindo** e o cronômetro começa.

O que o botão faz depende do estado: se a OP estava Parada, ele retoma. Se voltou do retrabalho, inicia o retrabalho. Nos demais casos é o início normal.

Com a OP em **Setup**, o botão Iniciar fica apagado. A volta à produção é automática: acontece sozinha quando o lote é liberado no popup **Setup e Qualidade** (veja [Setup e primeira peça](topico:07-setup-e-primeira-peca)).

Se nenhuma operação estiver carregada, o sistema avisa: "Carregue e selecione uma operação antes de iniciar." (ou "...antes de apontar.").

Atenção: o **Iniciar** é livre, ou seja, a primeira peça não impede começar. A conferência da primeira peça é exigida na hora de **Finalizar**.

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
   - Setup obrigatório ainda não registrado: a dica traz a mensagem do sistema, por exemplo "Aponte o Setup desta operação para conferir a primeira peça antes de finalizar." Veja [Setup e primeira peça](topico:07-setup-e-primeira-peca).
3. Com a primeira peça pendente (Setup já registrado, conferência não concluída), o botão continua clicável. O clique não abre o popup de quantidades: só mostra o aviso do sistema. Em Solda e Pintura, o clique abre o popup **Primeira peça**.

## Atividade sem OP

1. Sem OP carregada, clique em **Iniciar**.
2. Abre "Atividade sem OP": "Iniciar uma atividade sem OP neste posto?" Responda **Sim** ou **Não**.
3. Para encerrar, clique em **Finalizar** (o nome do botão continua "Finalizar") e responda "Finalizar a atividade sem OP em andamento?"

## Mais de uma OP no mesmo posto

Qualquer posto aceita produzir várias OPs ao mesmo tempo. Cada uma tem seu card em Produção. Parar uma OP que já está produzindo e retomá-la também é permitido.

A exceção é **Setup** e **Retrabalho**: eles ocupam o posto inteiro. Enquanto houver OP em Setup ou Retrabalho, o sistema não deixa iniciar outra OP, e para entrar em Setup ou Retrabalho o posto precisa estar sem outra OP ativa. Também não dá para registrar parada de uma OP que ainda está na fila (nunca produziu). A mensagem aparece no quadro abaixo.

## Problemas comuns

| Mensagem ou situação | O que fazer |
|---|---|
| "Esta OP já foi apontada em outra estação." | A OP está em outro posto. Fale com a liderança. |
| "Há setup ou retrabalho em andamento neste posto. Finalize-o antes de iniciar outra OP." | Finalize o Setup ou o Retrabalho que está aberto. |
| "Recurso parado — {motivo}. Retome para voltar a apontar." | Clique em **Retomar produção**. |
| **Iniciar** apagado | Etapa não selecionada, OP já em andamento ou em Setup/Retrabalho, outro Setup/Retrabalho aberto no posto, ou primeira peça reprovada esperando o responsável. |
