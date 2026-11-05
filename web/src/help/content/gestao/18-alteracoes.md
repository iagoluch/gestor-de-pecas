---
titulo: Alterações (auditoria)
grupo: Início
ordem: 18
rotas: /inicio/alteracoes
---

Tela **IagoDev — Alterações**: "Quem mudou usuários, níveis, turnos, pausas, decisões de RNC e sugestões de manutenção. Só leitura." **Só a conta de administração** abre.

## Filtros

| Filtro | Opções |
|---|---|
| O quê | Tudo, Usuário, Nível de acesso, Turno, Pausa, Decisão de RNC, Sugestão de manutenção, Etapa do roteiro. |
| Quem | Nome ou id (até 80 caracteres). |
| De / Até | Datas. |

Botões: **Filtrar** (só aplica quando você clica) e **Limpar**. Clique em um título de coluna para ordenar.

## Lista "Mais recentes primeiro"

Mostra a contagem ("N alteração(ões)"). Quando chega a 200 registros, aparece o aviso "Mostrando as 200 mais recentes. Use os filtros para ver as anteriores."

| Coluna | Significado |
|---|---|
| Quando | Data e hora. |
| Quem | Quem fez. "Não informado" se faltar. |
| O quê | Tipo e chave do registro. |
| Ação | Criou, Alterou ou Excluiu. |
| Mudança | "Campo: antes → depois". Sem campos registrados: "Sem diferença nos campos registrados". |

Campo vazio aparece como "vazio". Campos que podem aparecer: Nome, Nível, Unidade, Ativo (Sim/Não), Rótulo, Nível base, Tipo, Início, Fim, Ordem, Setor, RNC (id), RNC, Decisão, Justificativa, Sugestão (id), Recurso, Início da parada, Situação (Sugerida, Aceita, Descartada) e Nota.

Valores em dinheiro não aparecem aqui (ficam na aba Diretoria).

## Limites

Só as entidades do filtro "O quê" são registradas. Outras mudanças não aparecem aqui.

## Problemas comuns

| O que aparece | O que fazer |
|---|---|
| "Não foi possível carregar as alterações" com "Esta tela é exclusiva da conta de administração." | Entre com a conta admin. |
| "Não foi possível carregar as alterações" com "Tente novamente." | Use o botão de tentar de novo. |
| "Nenhuma alteração registrada para este filtro." | Amplie o período ou limpe os filtros. |

Relacionados: [Cadastro](topico:20-cadastro), [Turnos](topico:17-turnos), [Pausas](topico:13-pausas).
