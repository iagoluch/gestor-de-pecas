---
titulo: Painéis - Andon
grupo: Painéis
ordem: 98
rotas: /andon, /inicio/andon
---

Tela **Painéis Operacionais — Andon**. Painel ao vivo da fábrica, feito para TV. Mostra cada máquina com cor, tempo no estado, OP e indicadores. O endereço antigo `/inicio/andon` leva para `/andon`.

## Dois jeitos de ver

| Quem abre | O que aparece |
|---|---|
| Gestão | Quadro completo, com todos os setores ao mesmo tempo e menu lateral para voltar. |
| Login da TV (perfil Andon) | **Rodízio**: um setor por vez em tela cheia. Sem botões. |

Atualiza em tempo real. Se o tempo real cair, relê a cada 30 segundos. Barra de status: "Atualizado às hh:mm". Com falha: "Sem conexão com o servidor — dados de hh:mm. Reconectando automaticamente."

## Rodízio da TV

1. Começa pela visão geral, que é o [mapa da fábrica](topico:99-paineis-mapa-fabrica).
2. A cada **12 segundos** troca de etapa.
3. Depois mostra um setor por vez (só setores com recurso ativo).
4. No fim volta ao mapa.

Parada de máquina não prende o rodízio. Com menos de 2 setores, fica só na visão geral.

## Balões de aviso (só na TV)

- Aparecem no canto superior esquerdo, no máximo 3 ao mesmo tempo, cada um some em 8 segundos.
- Avisam mudança de estado de **máquina que está fora da tela atual**: produção, parada, setup, retrabalho, fila, atividade sem OP.
- Mostram nome do recurso, setor, novo estado, "Motivo: …" e "OP x • operador".
- Não avisam fora de turno, sem demanda ou desconhecido, nem a primeira carga.

## Quadro do gestor

Duas colunas: Corte e Solda de um lado, Caldeiraria e Pintura do outro. Cada painel mostra o nome do setor e "RECURSOS ATIVOS (N)". Na visão geral da TV aparece também "N EM PARADA". Sem máquina: "Nenhum recurso ativo". A Solda agrupa por Aço, Alumínio, Robô, Ferramentaria e Protótipo.

## Cartão de cada máquina

- Nome e código.
- Estado e cronômetro do tempo no estado (conta ao vivo). Em parada mostra o motivo; sem motivo: "Motivo não informado".
- Botão **OEE (%)**: abre o painel lateral com detalhes (veja abaixo).
- **Disp.** (disponibilidade), **Perf.** (performance) e **FTT** (peças boas de primeira). Traço (—) se não há dado; passe o mouse para ver o motivo.
- Corte: Tarefa, Plano e "Chapa x · nesting n".
- Demais setores: OP • operação, Produto e "+ N OP(s) simultânea(s)". Sem OP, mostra a atividade.

Quando uma máquina muda de estado, o cartão pisca por 1,5 segundo.

## Cores

| Cor | Estado |
|---|---|
| Verde | Produção |
| Vermelho | Parada não planejada |
| Amarelo/âmbar | Parada planejada |
| Azul-ciano | Setup |
| Marrom escuro | Retrabalho |
| Verde-azulado | Atividade sem OP |
| Cinza | Desconhecido |
| Cinza com borda tracejada | Sem demanda: fora de turno, sem hora extra e sem ninguém trabalhando |

Fila e fora de turno também existem como estados. Se a parada é planejada ou não, quem decide é o sistema pelo motivo apontado.

## Painel lateral "Indicadores de <máquina>"

Estado atual, Tempo no estado, Início. OEE e componentes (OEE, Disponibilidade, Performance, FTT; "Não disponível" se sem dado). Ordem e produção: OP, Operação, Produto, Operador, Quantidade boa, Quantidade prevista, Refugo, Retrabalho, OPs ativas no recurso e lista de OPs simultâneas.

## Quem pode ver

Gestão (quadro completo) e o perfil de TV Andon (rodízio). Veja [perfis e acessos](topico:02-perfis-e-acessos).

## Problemas comuns

- **"Nenhum recurso ativo no Andon."** ou "Nenhum recurso disponível para o Andon.": nada ativo agora.
- **"Sem conexão com o servidor…"**: a TV perdeu a rede; volta sozinha.
- **Máquina cinza tracejada**: sem demanda; não é falha.
- **Balão não apareceu**: só aparecem para máquinas fora da tela atual.
- **Números de OEE/Disp./Perf./FTT**: a origem do cálculo está em [OEE](topico:70-analises-oee); detalhes finos, confirmar com a liderança.
