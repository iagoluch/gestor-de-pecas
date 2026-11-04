---
titulo: A tela do posto
grupo: Tela do posto
ordem: 3
rotas: /operador
---

Esta é a tela onde você registra o trabalho da máquina ou estação. Ela serve para os setores que apontam por OP. O Corte e o Destaque têm telas próprias: veja [Corte](topico:20-corte) e [Destaque](topico:30-destaque).

## De cima para baixo

1. **Topo** (relógio, máquina, ?, tema, sair): veja [Entrar e o topo da tela](topico:01-login-e-topo).
2. **Barra de estado do posto**: diz o que o posto está fazendo agora.
3. **Campo "Código da OP"** e botão **Carregar roteiro**: veja [Carregar a OP e o roteiro](topico:04-carregar-op-e-roteiro).
4. **Roteiro completo da OP**: lista das operações.
5. **Botões de ação** (barra "Ações operacionais"): veja [Iniciar, parar e finalizar](topico:05-iniciar-parar-finalizar).
6. **Cards "Produção", "Fila de Ordem" e "Histórico"**: veja [Cards, fila e histórico](topico:10-cards-fila-e-historico).
7. **Desenho da peça**: veja [Desenho da peça](topico:12-desenho-da-peca).
8. Botão flutuante **Chamar**: veja [Chamar alguém](topico:11-chamar-alguem).

## Barra de estado do posto

Mostra o estado e um cronômetro (HH:MM:SS) contando desde que o estado começou. Abaixo pode aparecer o detalhe, no formato "OP x · motivo · desde HH:MM".

| Estado | Significado |
|---|---|
| **Produzindo** | Há OP em processo neste posto. |
| **Parado** | O posto está parado. O detalhe mostra o motivo. |
| **Setup** | Preparação da máquina em andamento. |
| **Retrabalho** | Peças sendo retrabalhadas. |
| **Atividade sem OP** | Você está numa atividade que não é de nenhuma OP. |
| **Aguardando OP** | O posto está livre, esperando uma OP. |
| **Fora do turno** | Fora do horário de trabalho cadastrado. |
| **Sem demanda** | Não há OP para este posto. |
| **Sem apontamento** | O sistema não tem registro do posto. No Corte e no Destaque, é o que aparece quando não há nada em andamento. |

Cores e etiquetas: veja [Estados e cores](topico:90-estados-e-cores).

## Avisos que aparecem na tela

| Aviso | Significado | O que fazer |
|---|---|---|
| "Recurso parado — {motivo}. Retome para voltar a apontar." (vermelho) | O posto está em parada. | Clique em **Retomar produção**. |
| "Há setup ou retrabalho em andamento neste posto. Finalize-o antes de iniciar outra OP. OP x (status)." | Outra OP está em Setup ou Retrabalho e trava o posto. | Entre nessa OP e finalize o setup ou o retrabalho. |
| "Atualizando produção e fila…" | A tela está buscando dados novos. | Aguarde. |
| "Atualização temporariamente indisponível. Os dados exibidos podem estar desatualizados." | A tela perdeu contato com o servidor. | Aguarde. Se demorar, avise a liderança. Não confie nos números até voltar. |

## Troca de turno

Quando alguém assume o posto com Setup ou Retrabalho aberto, precisa entrar no posto para retomar ou finalizar. O sistema não deixa iniciar outra OP antes. Regras detalhadas de turno: confirmar com a liderança.
