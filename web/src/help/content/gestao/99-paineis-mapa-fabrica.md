---
titulo: Painéis - Mapa da fábrica
grupo: Painéis
ordem: 99
rotas: /mapa-fabrica, /inicio/mapa-fabrica
---

Tela **Painéis Operacionais — Mapa da fábrica**. Desenho da planta com cada máquina colorida pelo estado atual. O endereço antigo `/inicio/mapa-fabrica` leva para `/mapa-fabrica`. É a mesma visão geral que abre o rodízio do [Andon](topico:98-paineis-andon) na TV.

## O que você vê

A planta mostra as áreas (por exemplo estoque de chapas, plasma, rebarbação, robô, expedição, almoxarifado, destaque, laser, dobra, usinagem, projetos/ferramentaria, solda, serras). Dentro delas, cada máquina é um bloco colorido.

Todos os postos apontáveis aparecem, estando ativos ou não.

## Legenda das cores

| Cor | Significa |
|---|---|
| Produção | Máquina produzindo. |
| Setup | Em preparação. |
| Parada não planejada | Parada sem programação. |
| Parada planejada | Parada prevista. |
| Retrabalho | Fazendo retrabalho. |
| Atividade sem OP | Trabalhando sem OP. |
| Sem demanda | Cinza. Também cobre fila, fora de turno e desconhecido. |
| Área sem apontamento | Área da planta sem posto apontável. |

Se alguma máquina não tem posição na planta, aparece "N recurso(s) fora da planta".

## Passar o mouse (só gestão)

Mostra um cartão com: recurso e código; estado e duração; motivo ou atividade; OEE, Disp., Perf., FTT; OP, Produto, Operação, Operador e Boas ÷ planejadas; Tarefa e Plano do Corte; OPs ativas.

Na TV não há interação nem botões.

## Quem pode ver

Gestão. Veja [perfis e acessos](topico:02-perfis-e-acessos).

## Problemas comuns

- **Máquina fora da planta**: o posto ainda não tem lugar desenhado. Confirmar com a liderança/TI.
- **Tudo cinza**: fora de turno ou sem demanda. Veja [turnos](topico:17-turnos).
