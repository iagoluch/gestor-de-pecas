---
titulo: Finalizar e informar quantidades
grupo: Tela do posto
ordem: 9
rotas:
---

Ao clicar em **Finalizar**, abre o popup **Finalizar produção**.

## O que o popup mostra

| Linha | Significado |
|---|---|
| Produto e Descrição | A peça da OP. |
| QTD planejada | Quanto a OP pede. |
| Boas já registradas | Peças boas já lançadas antes. |
| Refugo já registrado | Refugo já lançado antes. |
| Quantidade atendida | O que já conta como feito. |
| Saldo | O que ainda falta. |

Texto do popup: "O saldo é reduzido por peças boas + refugo. Retrabalho permanece pendente e não atende o planejado."

## Campos

| Campo | O que informar |
|---|---|
| **Peças boas** | Quantas peças boas você fez agora. Vazio vale 0. |
| **Refugo** | Quantas peças foram perdidas. Padrão 0. |
| **Crachá do responsável que autoriza o refugo** | Só aparece se refugo for maior que 0. Quem autoriza passa o crachá. O botão **Chamar responsável** abre o chamado. |
| **Crachá do operador** | Passe o seu crachá e clique em **+** (ou Enter) para adicionar. |
| **Operadores adicionados** | Lista de quem trabalhou. O **×** remove. Vazio: "Nenhum operador adicionado." |

Se o crachá não existir: "Crachá não cadastrado ou inativo."

## Passos

1. Digite **Peças boas** e, se houver, **Refugo**.
2. Se houver refugo, o responsável informa o crachá dele.
3. Passe seu crachá em **Crachá do operador** e clique em **+**.
4. Clique em **Confirmar finalização**.

## Quando o botão Confirmar finalização fica apagado

O motivo aparece escrito:

| Mensagem | O que fazer |
|---|---|
| "Informe o crachá do operador e toque em + para confirmar." | Adicione seu crachá com o botão **+**. |
| "Informe a quantidade de peças boas ou de refugo." | Preencha ao menos um. (Se o saldo já está zerado, 0 e 0 é aceito.) |
| "Informe o crachá do responsável que autoriza o refugo." | O responsável precisa passar o crachá. |

## Avisos

- "A quantidade informada (N) passa do saldo de S peça(s). Confira antes de confirmar." É só um aviso: não bloqueia. Confira se digitou certo.
- Erros do sistema aparecem dentro do popup, em vermelho. Leia e corrija.

## Finalização parcial

Se você finalizou só parte da OP (finalização parcial), a OP continua carregada na tela. Se finalizou tudo, o campo "Código da OP" é limpo.

## Refugo no retrabalho

A mesma regra de crachá vale em [Retrabalho](topico:08-retrabalho).
