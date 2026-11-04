---
titulo: Retrabalho
grupo: Tela do posto
ordem: 8
rotas:
---

**Retrabalho** é consertar peças que saíram com defeito, sem fabricar de novo. Enquanto há retrabalho aberto, o posto fica travado para outras OPs (isso vale em todos os postos). A tela avisa: "Há setup ou retrabalho em andamento neste posto. Entre para retomá-lo ou finalizá-lo."

## O botão Retrabalho

O botão tem dois nomes:

| Nome | Quando |
|---|---|
| **Retrabalho** | A OP não está em retrabalho. |
| **Finalizar Ret.** | A OP está em Retrabalho. |

Fica apagado se não há operação selecionada que possa ser apontada (etapa não selecionável).

## Começar um retrabalho

1. Selecione a OP e a etapa.
2. Clique em **Retrabalho**.
3. Abre **Confirmar Retrabalho**. Confirme.
4. A barra de estado passa para **Retrabalho**.

Se a OP está bloqueada por primeira peça reprovada, clicar em **Retrabalho** abre o popup de bloqueio. Veja [Setup e primeira peça](topico:07-setup-e-primeira-peca).

## Finalizar o retrabalho

1. Clique em **Finalizar Ret.** Abre **Finalizar retrabalho**.
2. Texto do popup: "Das peças em retrabalho, quantas ficaram boas e quantas vão para refugo? Campo vazio vale 0. Depois disso a OP volta para Em processo."
3. Preencha:

| Campo | O que informar |
|---|---|
| **Peças boas (recuperadas)** | Quantas peças foram consertadas. |
| **Peças para refugo** | Quantas não têm conserto. |

4. Se informou refugo, preencha o crachá do responsável (veja [Finalizar e informar quantidades](topico:09-finalizar-quantidades-e-crachas)).
5. Clique em **Confirmar** (o botão se chama só "Confirmar", e não exige quantidade: só o crachá do operador e, havendo refugo, o do responsável).

A OP volta para **Em processo**.

## Regras importantes

- Com retrabalho aberto, **Finalizar** fica apagado. A dica é: "Encerre o retrabalho primeiro (Finalizar Ret.)."
- Retrabalho pendente não conta como peça atendida do planejado.
- Quem assume o posto com retrabalho aberto (por exemplo, na troca de turno) precisa entrar e finalizá-lo antes de iniciar outra OP. O sistema não tem regra especial de troca de turno para Setup/Retrabalho: eles continuam abertos até alguém finalizar. O que acontece com eles à noite ou no fim do turno: confirmar com a liderança.

## Problemas comuns

| Situação | O que fazer |
|---|---|
| Não consigo iniciar outra OP | Finalize o retrabalho aberto. |
| Erro de crachá | "Crachá não cadastrado ou inativo." Confira o número do crachá. |
