---
titulo: Cadastro de usuários e níveis
grupo: Início
ordem: 20
rotas: /inicio/cadastro
---

Tela **Admin — Cadastro**: "Login de quem acessa o sistema — a mesma tela que os funcionários usam para entrar." **Só a conta de administração** abre.

## Cartões

| Cartão | Significado |
|---|---|
| Usuários ativos | Quantos estão ativos. Embaixo: "N cadastrados". |
| Contas admin | Acesso total, incluindo Cadastro. |
| Inativos | Contas bloqueadas. |
| Sem conta admin | Sim ou Não. Se Sim, ninguém gerencia usuários nem contatos de chamada. |

## Filtros

Situação, Nível (agrupado por setor), Unidade ("Unidade X" e "Sem unidade"), Tela (Gestão, Apontamento, Manutenção, "Outras (Andon/Almoxarifado)") e a busca "Buscar por nome".

## Tabela "Usuários cadastrados"

Colunas: Nome, Nível, Unidade, Situação, Ações.

| Ação | O que acontece |
|---|---|
| **Editar** | Abre o formulário. |
| Desativar / Ativar | Desativar pede confirmação: a pessoa deixa de conseguir entrar. |
| Excluir | Pede confirmação. Apaga de vez, junto com conversas de IA, relatórios e agendamentos dessa conta. Não dá para desfazer. Para só bloquear, use Desativar. |

Na **sua própria conta**, Desativar e Excluir ficam bloqueados ("Sua própria conta: peça a outro administrador…"), e nível e Ativo não mudam.

## Criar ou editar usuário

1. Clique em **Novo usuário**.
2. **Nome** (obrigatório).
3. **Nível de acesso** (agrupado; um usuário novo começa em "Operador destaque"). O nível decide o que a pessoa vê: [Perfis](topico:02-perfis-e-acessos).
4. **Unidade** (texto livre, até 40 caracteres, ex.: 4).
5. **Senha** (novo usuário). Ao editar: "Nova senha (deixe em branco para manter a atual)".
6. **Ativo**. Salve.

A tela diz "Mínimo de 6 caracteres", mas contas da gestão exigem 8 no servidor. Use 8 ou mais. Veja [Entrar no sistema](topico:01-entrar-e-trocar-senha). Se a pessoa entrar com a senha padrão, será obrigada a trocá-la.

## Níveis personalizados

Tabela "Níveis personalizados": Nível, "Permissões de" e Excluir (só se nenhuma conta usar o nível).

1. Clique em **Novo nível**.
2. Dê o **Nome do nível** (até 60 caracteres).
3. Escolha em "Copiar as permissões de" o nível base (começa em "Gestor"; "Admin" não aparece na lista).
4. Clique em **Criar nível**.

A tabela "Níveis personalizados" só aparece depois que existe pelo menos um.

## Mensagens

| Mensagem | Significado |
|---|---|
| "Usuário criado." / "Usuário atualizado." / "Usuário excluído." | Deu certo. |
| "Nível criado." / "Nível excluído." | Deu certo. |
| "Não foi possível salvar o usuário." | Revise nome, nível e senha. |
| "Não foi possível excluir o usuário." | Tente de novo. |
| "Não foi possível criar o nível." / "Não foi possível excluir o nível." | Nome repetido ou nível em uso. |
| "Nenhum usuário no filtro atual" | Limpe os filtros. |
| "Nenhum usuário cadastrado" | Crie o primeiro para liberar o acesso. |

Mudanças aqui ficam registradas em [Alterações](topico:18-alteracoes).
