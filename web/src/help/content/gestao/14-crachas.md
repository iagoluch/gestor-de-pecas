---
titulo: Crachás
grupo: Início
ordem: 14
rotas: /inicio/crachas
---

Tela **IagoDev — Crachás**: "Crachás do chão de fábrica e quem está autorizado a liberar o retrabalho da primeira peça." **Só a conta de administração** abre. Outras contas veem "Acesso restrito ao administrador".

## Cartões

| Cartão | Significado |
|---|---|
| Crachás ativos | Quantos podem ser usados nos terminais. |
| Responsáveis autorizados | Quem libera o retrabalho da primeira peça. |
| Inativos | Crachás desligados. |
| Sem responsável | Sim ou Não. Se Sim: sem responsável, a OP bloqueada não é liberada. |

## Filtros

Situação, Perfil (Responsável por retrabalho ou Operador sem designação), Origem do cadastro e a busca "Buscar por crachá ou nome".

## Tabela "Crachás cadastrados"

Colunas: Crachá, Nome, Situação, Perfil (na tabela aparece "Responsável por retrabalho" ou "Operador"), Origem, Telegram (Vinculado ou Não vinculado) e Ações. A lista vem em ordem alfabética de nome. O botão **Novo crachá** fica no topo da tela.

Menu de ações:

| Ação | O que acontece |
|---|---|
| **Editar** | Abre o formulário. |
| Tornar responsável / Remover responsável | Dá ou tira a autorização. Só pede confirmação ao remover. |
| Gerar código do Telegram | Só para crachá ativo. Mostra um código de uso único para vincular. |
| Desvincular Telegram | Pede confirmação. O chat deixa de consultar a fábrica pelo bot e recebe um aviso. |
| Ativar / Desativar | Desativar pede confirmação: o crachá deixa de ser aceito nos terminais. |

## Criar ou editar

1. Clique em **Novo crachá**.
2. Preencha **Crachá** (obrigatório; não muda depois de criado) e **Nome** (obrigatório).
3. Marque **Ativo** e, se for o caso, "Autorizado a liberar retrabalho da primeira peça".
4. Salve. Aviso: "Crachá salvo. A designação já vale para o próximo chamado."

O responsável **não tem login**. Ele é identificado pelo crachá.

## Vincular o Telegram

1. No menu da linha, escolha **Gerar código do Telegram**.
2. O diálogo "Código de vínculo do Telegram" mostra o comando `/vincular CÓDIGO`, o tempo de validade em minutos e que serve uma vez só.
3. A pessoa envia o comando ao bot. Anote o código na hora: ele não reaparece.

## Problemas comuns

| O que aparece | O que fazer |
|---|---|
| "Não foi possível salvar o crachá. Confira o código e o nome." | Revise os campos. |
| "Não foi possível gerar o código. Se o crachá já tem Telegram vinculado, desvincule antes." | Desvincule e gere de novo. |
| "Não foi possível desvincular o Telegram." | Tente de novo. |
| "Nenhum crachá no filtro atual" | Limpe os filtros. |
| "Nenhum crachá cadastrado" | Sem crachá, nenhuma exceção operacional pode ser autorizada. Cadastre. |

Relacionados: [Chamadas do IagoDev](topico:16-chamadas-iagodev), [Cadastro](topico:20-cadastro).
