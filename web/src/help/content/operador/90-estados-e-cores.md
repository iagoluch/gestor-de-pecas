---
titulo: Estados e etiquetas
grupo: Referência
ordem: 90
rotas:
---

Resumo dos estados que aparecem no sistema. Os tons abaixo são os do tema claro; no tema escuro as cores ficam mais claras, mas a ideia é a mesma.

## Estado do posto (barra de estado)

| Estado | Significado | Cor da barra |
|---|---|---|
| Produzindo | OP em processo. | Verde |
| Parado | Posto parado, com motivo. | Vermelho |
| Setup | Preparação em andamento. | Azul-esverdeado |
| Retrabalho | Retrabalho em andamento. | Marrom escuro |
| Aguardando OP | Livre, esperando OP. | Amarelo |
| Sem apontamento | Sem registro (também aparece em Corte e Destaque quando o posto está livre). | Amarelo ou cinza |
| Atividade sem OP | Atividade fora de OP. | Cinza |
| Fora do turno | Fora do horário. | Cinza |
| Sem demanda | Sem OP para o posto. | Cinza |

## Cartões de recurso (escolha do posto)

| Estado | Significado | Cor |
|---|---|---|
| Livre | Nenhuma OP. | Selo verde |
| Em uso | "Em uso por N OP(s)". | Borda e selo amarelos |
| Ocupada | Setup ou retrabalho aberto. | Borda e fundo vermelhos |

Os cartões nunca ficam apagados: mesmo um posto ocupado pode ser aberto, para retomar ou finalizar o que está em andamento.

## Etapas do roteiro

Concluída (verde), Atual (azul), Próxima. A etapa selecionada ganha borda laranja e um visto. Veja [Carregar a OP e o roteiro](topico:04-carregar-op-e-roteiro).

## Cards da OP

Em processo (verde), Parada (vermelho), Setup, Retrabalho, Aguardando (padrão). Veja [Cards, fila e histórico](topico:10-cards-fila-e-historico).

## Corte

Tarefa: Aguardando, Em processo, Finalizado. Plano: AGUARDANDO CORTE (amarelo), EM CORTE (verde), CORTE PARCIAL (amarelo), DISPONÍVEL PARA DESTAQUE (azul), FINALIZADO (cinza). Veja [Corte](topico:20-corte).

## Motivos de parada

No seletor de motivos, o motivo **planejado** (almoço, pausa, reunião, limpeza, manutenção preventiva...) aparece em tom de atenção (amarelo). Os demais (**não planejados**) aparecem em vermelho. Veja [Parada e motivos](topico:06-parada-e-motivos).

## Destaque

Corte concluído, Corte parcial (tarefa). Aguardando destaque, Destaque em execução, Destaque parado, Destaque concluído (plano). Histórico: Em execução, Parada, Finalizada, Aguardando. Veja [Destaque](topico:30-destaque).

## Qualidade

| Item | Valores |
|---|---|
| Cota | Conforme, Não conforme, Informe a medida |
| Peça | Aprovada, Retrabalho, Refugo |
| Primeira peça | Conforme (libera o lote), Retrabalho (bloqueia), Refugo (nova primeira peça) |

Veja [Qualidade e inspeção](topico:40-qualidade-e-inspecao).

## Cores de aviso

- Vermelho: erro ou posto parado.
- Amarelo: atenção (ex.: motivo de parada classificado como de atenção).
- Verde: sucesso ou conforme.
- Azul: informação.
