---
titulo: Carregar a OP e o roteiro
grupo: Tela do posto
ordem: 4
rotas:
---

## Campo "Código da OP"

| Item | O que faz |
|---|---|
| Campo **Código da OP** | Digite ou escaneie o código da OP (dica "Digite ou escaneie a OP"). O cursor já começa aqui. Ao carregar, as letras viram maiúsculas. |
| Botão **Carregar roteiro** | Busca a OP e mostra as operações dela. |

Passos:

1. Escaneie ou digite o código da OP.
2. Clique em **Carregar roteiro** (ou Enter).
3. O roteiro aparece em "Roteiro completo da OP".

Para limpar, apague o campo. A tela responde "Produção e fila atualizadas." e volta ao normal.

Clicar em um card (Produção, Fila ou Histórico) também carrega aquela OP. Isso só carrega: não registra nada. A tela avisa "OP {x} selecionada no card."

## Roteiro completo da OP

Lista numerada. Cada linha é "número - descrição" e tem uma etiqueta:

| Etiqueta | Significado |
|---|---|
| **Concluída** | Etapa já finalizada. Não pode ser reaberta. |
| **Atual** | É a etapa em que a OP está agora. |
| **Próxima** | Ainda não chegou a vez. |

Etapas que você não pode apontar neste posto ficam desabilitadas (apagadas). A etapa automática de inspeção não aparece na lista.

### Escolher uma etapa

- Clique na etapa que você vai apontar.
- Se for a etapa **atual**, nada é perguntado. A tela diz "Etapa atual selecionada: X."
- Se for **outra** etapa, abre o popup **Confirmar operação**:

| Campo do popup | O que mostra |
|---|---|
| OP | O código da OP. |
| Etapa atual da OP | Onde a OP está de verdade. |
| Você selecionou | A etapa que você clicou. |

Pergunta: "Deseja realmente apontar esta operação?" Botões: **Cancelar** (nada muda) e **Sim, apontar esta operação**.

## Mensagens depois de carregar

| Mensagem | Significado |
|---|---|
| "Carregando roteiro…" | Aguarde a lista das etapas. |
| "OP encontrada. Etapa atual: X." | Tudo certo. |
| "OP encontrada. Etapa atual: X. Ainda não disponível para {setor}." | A OP existe, mas ainda não chegou ao seu setor. Não dá para apontar. |
| "Roteiro concluído. Etapas finalizadas não podem ser reabertas." | Todas as etapas terminaram. |
| "Operação X selecionada. Ela não é a etapa atual da OP." | Você escolheu uma etapa diferente da atual. |
| "Buscando OP no TOTVS..." | A OP não estava no Gestor. O sistema procura no ERP (uma vez por OP). |
| "OP {x} não encontrada. Confira o código." | Código errado ou OP não existe. |
| "Não foi possível carregar a OP {x}." | Falha na busca. Tente de novo. |
| "Informe o código da OP." | Você clicou em Carregar com o campo vazio. |
| "OP não encontrada" (embaixo do campo) | Você tentou parar o posto com uma OP que não existe. |
| "Carregue e selecione uma operação antes de iniciar." (ou "...apontar." / "...registrar a primeira peça.") | Você clicou em um botão sem ter carregado a OP e escolhido a etapa. |

## Problemas comuns

- **A OP não aparece**: confira o código. Se a OP é nova, espere a busca no TOTVS terminar.
- **Etapa desabilitada**: ela não é do seu posto ou já foi concluída.
- **Não consigo iniciar**: veja [Iniciar, parar e finalizar](topico:05-iniciar-parar-finalizar).
