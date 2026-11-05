---
titulo: Pausas
grupo: Início
ordem: 13
rotas: /inicio/pausas
---

Tela **Painéis Operacionais — Pausas**: "Horários em que o sistema interrompe o apontamento por setor." Aqui você cadastra almoço, café e outras pausas de cada setor.

Sem pausa configurada, o sistema não interrompe o apontamento sozinho.

## Cartões do topo

| Cartão | O que mostra |
|---|---|
| Pausas ativas | Quantas estão configuradas e ativas. |
| Setores cobertos | Quantos setores têm pausa, "de 13 setores". |
| Almoço | Setores com pausa ativa cujo nome contém "almo". |
| Café | Mesma ideia para pausas de café. |

## Filtros

Os filtros ficam salvos no seu navegador.

| Filtro | Opções |
|---|---|
| Setor | Um dos 13 setores. |
| Tipo de pausa | Almoço, Café, Ginástica laboral, Reunião, Limpeza, Treinamento, ou a própria descrição. O tipo é deduzido por palavra no nome. |
| Situação | Ativa ou Inativa. |
| Busca | "Buscar por setor, pausa ou horário". |
| **Limpar** | Zera os filtros. |

Um resumo mostra "N de M pausas no recorte atual" ou "N pausas configuradas".

## Tabela "Pausas por setor"

| Coluna | Significado |
|---|---|
| Setor | Onde a pausa vale. |
| Pausa | A descrição. |
| Tipo | Só aparece quando acrescenta informação. |
| Início e Fim | Horário. |
| Duração | Em minutos. "Horário a confirmar" se faltar dado. Pausa que vira o dia soma 24 h. |
| Situação | Ativa ou Inativa. |
| Ações | **Editar** e um menu com Desativar/Ativar e Remover. |

## Criar ou editar

1. Clique em **Nova pausa** (padrão 12:10 às 12:52) ou em **Editar** na linha.
2. Escolha o **Setor** (Corte, Dobra, Usinagem, Serra, Caldeiraria, Solda Aço, Solda Alumínio, Solda Robô, Proj. Ferramentaria, Protótipo, Pintura, Montagem, Destaque).
3. Escreva a **Descrição** (obrigatória, ex.: "Almoço, Café, Ginástica…").
4. Ajuste **Início** e **Fim**.
5. Deixe **Ativa** marcada se vale já.
6. Salve.

Ao salvar: "Pausa salva. O próximo ciclo já usa o novo horário."

Desativar e ativar pedem confirmação. **Remover** pede confirmação com o aviso "Esta ação não pode ser desfeita."

## Quem pode

Qualquer conta da gestão abre a tela e grava pausas. Contas presas a um setor (líder e supervisor) só veem e mexem nas pausas do próprio setor, porque elas mudam o OEE dele. Se tentar mexer em pausa de outro setor, o servidor responde "Essa pausa é de outro setor.". Toda alteração fica registrada na tela [Alterações](topico:18-alteracoes).

O serviço de turno lê as pausas ativas a cada ciclo e gera sozinho o início e o fim de cada intervalo. Se um setor desativar todas as suas pausas, nenhuma é aplicada a ele. Se a pausa conta como "Parada planejada" nos indicadores de cada tela: confirmar com a liderança.

## Problemas comuns

| O que aparece | O que fazer |
|---|---|
| "Não foi possível salvar a pausa. Confira o horário informado." | Revise início e fim. |
| "Não foi possível remover a pausa." | Tente de novo; persistindo, fale com a administração. |
| "Nenhuma pausa no filtro atual" | Clique em **Limpar**. |
| "Nenhuma pausa configurada" | Cadastre a primeira com **Nova pausa**. |

Relacionado: [Turnos](topico:17-turnos).
