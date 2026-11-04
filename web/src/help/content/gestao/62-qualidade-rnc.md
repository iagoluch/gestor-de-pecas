---
titulo: Qualidade - Decisão de RNC
grupo: Qualidade
ordem: 62
rotas: /qualidade/rnc
---

A tela **Qualidade — Decisão de RNC** serve para registrar o que fazer com a peça de uma RNC (Relatório de Não Conformidade, aberto quando uma peça sai fora do padrão). A decisão fica no histórico e **não bloqueia nada**: é só registro interno.

## Quem pode ver

Só **Qualidade** e **Admin**. Os outros veem "Acesso restrito à Qualidade". Se o servidor negar: "Seu perfil não tem acesso às decisões de RNC. Só a Qualidade e a administração usam esta tela."

## Alternar a lista

| Aba | O que mostra |
|---|---|
| Sem decisão | Só as RNCs que ainda não têm decisão. É a aba que abre primeiro. |
| Todas | Todas as RNCs, com ou sem decisão. |

A tela mostra no máximo as **100 mais recentes**. Quando chega nesse limite, avisa "Mostrando as 100 mais recentes." O contador "N RNC(s)" fica no canto do cartão.

## Colunas da lista

| Coluna | O que significa |
|---|---|
| RNC | Código da RNC. |
| Aberta em | Data e hora em que foi aberta. |
| Produto / OP | Produto e OP da peça. "Não informado" se faltar. |
| Resultado da peça | Como o inspetor classificou a peça (por exemplo REFUGO ou RETRABALHO), em etiqueta colorida. "Peça não encontrada" se o registro da peça não existe mais. |
| Decisão vigente | A decisão em vigor, ou "Sem decisão". |
| Botão | **Decidir** (sem decisão) ou **Rever** (já tem decisão). |

## Registrar uma decisão

1. Clique em **Decidir** (ou **Rever**) na linha da RNC.
2. Abaixo aparece o cartão "Decisão — código". Ele mostra o motivo da RNC e como a peça foi registrada.
3. Escolha a **Decisão**.
4. Escreva a **Justificativa** (de 3 a 500 caracteres).
5. Clique em **Registrar decisão**. O botão só liga com decisão escolhida e justificativa com pelo menos 3 caracteres.

| Decisão | Uso |
|---|---|
| Usar como está | A peça segue como está. |
| Retrabalhar | A peça volta para ser refeita. |
| Sucatear | A peça é descartada. |
| Quarentena | A peça fica separada, aguardando análise. |

Ao registrar, vem a mensagem "Decisão X registrada para código."

### Aviso de contradição

O sistema grava a decisão **mesmo se contradizer** a classificação do inspetor, mas mostra um aviso para você confirmar. Os casos:

- Peça REFUGO e decisão "Usar como está".
- Peça REFUGO e decisão "Retrabalhar".
- Peça RETRABALHO e decisão "Usar como está".

Mensagem exemplo: "Decisão registrada. Atenção: A peça foi registrada como REFUGO na inspeção, mas a decisão é usar como está. A decisão foi gravada; confirme se é isso mesmo." As demais combinações não geram aviso.

## Histórico

Embaixo do cartão há o histórico da RNC: uma linha por decisão com a decisão, "(vigente)" na atual, quem decidiu, quando e a justificativa. Se não houver: "Ainda sem decisão registrada." Decisões antigas não são apagadas. Uma nova decisão passa a ser a vigente.

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| Esta RNC não existe mais. A lista foi atualizada. | A RNC foi removida; escolha outra. |
| Escolha a decisão e escreva a justificativa (de 3 a 500 caracteres). | Complete os dois campos. |
| Não foi possível registrar a decisão. Tente novamente. | Falha geral; repita. |
| Não foi possível acessar o servidor. Tente novamente. | Falha de rede. |
| Não foi possível carregar as RNCs | Clique em **Tentar novamente**. |
| Não foi possível carregar o histórico desta RNC. | Feche e reabra a RNC. |
| Nenhuma RNC aguardando decisão. / Nenhuma RNC registrada. | Lista vazia. |

Veja também: [Cotas padrão](topico:60-qualidade-cotas) e [Qualidade nas Análises](topico:73-analises-qualidade).
