---
titulo: Turnos
grupo: Início
ordem: 17
rotas: /inicio/turnos
---

Tela **IagoDev — Turnos**: "Horários em que o sistema fecha e reabre o apontamento automaticamente." **Só a conta de administração** abre.

## Cartões

| Cartão | Significado |
|---|---|
| Expediente | A janela ativa ("Janela oficial") ou "Não configurado". |
| Horas extras ativas | "de N cadastradas". |
| Faixas fora de turno | "Horários sem apontamento". |
| Turnos cadastrados | Total. |

## Como o sistema trata cada tipo

- **Hora extra no fim do expediente** (ex.: H2 17:30 às 21:30): fecha o apontamento sozinha ao terminar.
- **Hora extra que termina quando o expediente começa** (ex.: H1 06:00 às 08:00): não tem corte próprio. Quem já trabalha continua visível e não vira "Sem demanda".
- **Fora de turno** (ex.: 21:30 às 06:00): ninguém trabalha. Recurso parado nessa faixa não conta como "Sem demanda".

Regra da planta: turno único, com hora extra também no fim de semana. O expediente oficial abre só nos dias de trabalho da planta. Se o sistema ficou desligado, a recuperação dos fechamentos e aberturas atrasados cobre um fim de semana inteiro.

## Tabela "Turnos configurados"

Colunas: Ordem, Nome, Tipo (Expediente (janela oficial), Hora extra, Fora de turno), Início, Fim ("(dia seguinte)" quando o fim é menor que o início), Situação e Ações.

| Ação | O que acontece |
|---|---|
| **Editar** | Abre o formulário. |
| Ativar / Desativar | Desativar pede confirmação: deixa de abrir e fechar o apontamento a partir do próximo ciclo. |
| Remover | Pede confirmação. |

## Criar um turno

1. Clique em **Novo turno** e dê um nome (sugestão: "Turno A").
2. Confira as faixas: H1 (06:00 às 08:00), Oficial (08:00 às 17:30, obrigatória), H2 (17:30 às 21:30) e Fora de turno (21:30 às 06:00).
3. Desmarque as faixas que o turno não tem ("Este turno tem X").
4. Salve. O sistema cria uma linha "Nome Faixa" para cada faixa, ligada ao expediente.

Se já existe um expediente ativo, o turno novo é salvo **desativado**, porque só um expediente fica ativo por vez.

## Editar

Campos: Nome, Tipo, Turno oficial (obrigatório para hora extra e fora de turno), Início, Fim, Ordem (1 a 99) e Ativo.

## Mensagens

| Mensagem | Significado |
|---|---|
| "Turno salvo. O próximo ciclo já usa o novo horário." | Gravou. |
| "Turno salvo desativado, porque já existe um expediente ativo." | Ative-o depois de desativar o outro. |
| "Não foi possível salvar o turno. Confira o nome, o tipo e o horário informados." | Revise. |
| "Turno removido." / "Não foi possível remover o turno." | Resultado da remoção. |
| "Nenhum turno configurado" | O sistema usa a janela oficial homologada (08:00 às 17:30, com H1 e H2). |

Relacionado: [Pausas](topico:13-pausas), [Alterações](topico:18-alteracoes) (registra quem mudou turnos).
