---
titulo: Produção - Produção realizada
grupo: Produção
ordem: 47
rotas: /producao/realizada
---

Tela **Produção — Produção realizada**. Frase de apresentação: "Somente peças boas compõem a produção; perdas permanecem em grandezas separadas."

Ela responde: **quanto foi produzido no período e quanto se perdeu?**

## Filtros

Barra de filtros global: período, Setor e Mais filtros (veja [Filtros globais](topico:04-filtros-globais)).

## Botões de exportação

No cabeçalho há dois botões que baixam um arquivo Excel (.xlsx) com os filtros atuais:

| Botão | Arquivo |
|---|---|
| Export técnico | relatorio_producao_tecnico.xlsx |
| Export simples | relatorio_producao_simples.xlsx |

Durante a geração o botão mostra "Gerando…". Se falhar: "Não foi possível gerar o Excel." seguido do motivo.

O conteúdo exato de cada planilha não foi conferido para este manual. Confirmar com a liderança.

## Cartões do topo

Clique no número para ver de onde ele vem.

| Cartão | O que mostra | Observação |
|---|---|---|
| Produção boa | Total de peças boas. Detalhe: o motivo informado pelo sistema sobre a fonte do dado. | Verde. |
| Refugo | Total de peças refugadas. | Vermelho. |
| Retrabalho | Total de peças em retrabalho. | Amarelo. |
| Taxa de refugo | Refugo ÷ (boas + refugo) × 100. Detalhe: "N recursos no período". | Sem registros, mostra a frase de "sem registros". |
| OPs | Quantidade de OPs com produção no período. | |

Se o período não tem registros, os números dão lugar a uma frase explicando que não há dados. Isso é diferente de zero.

## Bloco "Peças boas por setor"

Gráfico de barras. Cada barra é um setor, com o rótulo "N peças". Sem dados, aparece uma mensagem de vazio com o motivo.

## Bloco "Qualidade por setor"

| Coluna | O que mostra |
|---|---|
| Setor | O setor. |
| Boas | Peças boas do setor. |
| Refugo | Refugo do setor. |
| Retrabalho | Retrabalho do setor. |

Sem dados no período, a tabela dá lugar a uma mensagem de vazio com o motivo informado pelo sistema.

## Quem vê

Qualquer conta da gestão. Líder e supervisor veem só o próprio setor.

## Redirecionamento

O endereço antigo `/relatorios/producao` abre esta tela.

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| Frase de "sem registros" no lugar dos números | Não há produção apontada no período. | Amplie o período. |
| Gráfico vazio com motivo | Nenhum setor tem peças boas no período. | Leia o motivo. |
| Não foi possível gerar o Excel. | A exportação falhou. | Tente de novo. Se persistir, avise a TI. |

## Veja também

- [Planejado × Realizado](topico:48-producao-planejado-realizado).
- [Execução das OPs](topico:46-producao-execucao-das-ops).
