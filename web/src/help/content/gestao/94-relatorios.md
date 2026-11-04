---
titulo: Relatórios
grupo: Relatórios e rastreabilidade
ordem: 94
rotas: /relatorios
---

Tela **Relatórios**. Mostra resumos prontos e gera planilhas Excel. Usa os mesmos números das outras telas gerenciais.

## Como usar

1. Escolha o tipo no seletor do topo (Gerencial, Perdas, Indicadores ou Dados analíticos).
2. Ajuste os [filtros globais](topico:04-filtros-globais).
3. Confira os cartões e a tabela.
4. Clique em **Export técnico** ou **Export simples** para baixar o Excel.

O tipo escolhido fica no endereço (`?tipo=`). Os endereços antigos (gerencial, perdas, indicadores, dados analíticos) abrem esta tela já no tipo certo.

## Botões de exportação

| Botão | O que vai no arquivo |
|---|---|
| Export técnico | Todas as abas de detalhe (veja por tipo abaixo). |
| Export simples | Uma aba só, "Resumo", que cabe em uma folha A4 paisagem. |

Durante a geração o botão mostra "Gerando…". Se falhar: "Não foi possível gerar o Excel." seguido do motivo.

O Excel só apresenta os números; não recalcula nada. Traço (—) significa dado não disponível, nunca zero.

Nome do arquivo: confirmar com a liderança/TI (a tela e o servidor sugerem nomes parecidos, no formato relatório_tipo_modo ou gestor_tipo_data).

## Tipo Gerencial

Frase: "Resumo executivo a partir das mesmas fontes das telas gerenciais."

- Cartões: Produção boa, Refugo, Retrabalho, OEE. Clique no valor para ver como foi calculado.
- Tabela Setores: Setor, Produção boa, Refugo, Retrabalho, Tempo produtivo.
- Planilha técnica: Visão Geral, Setores, Recursos, Perdas.
- Planilha simples (Relatório Gerencial): OEE, Produção boa, Disponibilidade, Performance, FTT, OPs executadas e ranking "Produção boa por setor".

## Tipo Perdas

Frase: "Paradas e qualidade sem conversão silenciosa de ausência em zero."

- Cartões: Tempo de parada (com média por recurso), Ocorrências, Refugo, Retrabalho.
- Tabela Paradas por motivo: Motivo e Tempo.
- Planilha técnica: Visão Geral, Motivos de Parada, Perdas por Setor, Refugo e Retrabalho, Paradas (detalhe).

## Tipo Indicadores

Frase: "Indicadores com disponibilidade e justificativa explícitas."

- Cartões: OEE, FTT, Tempo registrado, Utilização.
- Bloco Confiabilidade e capacidade: MTBF, MTTR, Quebras no período, Utilização. Mostra "Não disponível" ou "Não configurado" quando não há dado.
- Planilha técnica: Visão Geral, Recursos, Utilização, Confiabilidade, Evolução do OEE.

## Tipo Dados analíticos

Frase: "Conjunto analítico para conferência e exportação, sem editar a origem."

- Cartões: Ordens, Inconsistências, Nestings, Período.
- Tabela Ordens: OP, Produto, Operação, Setor, Recurso, Boas, Refugo, Status.
- Planilha técnica: Visão Geral, Ordens, Inconsistências, Diagnósticos, Nestings.

## Relatório de produção

Existe um tipo "produção" que só se exporta pela tela [Produção realizada](topico:47-producao-realizada).

## Quem pode ver

Somente usuários da gestão.

## Problemas comuns

- **"Não foi possível gerar o Excel."**: tente de novo com período menor. Se repetir, avise a TI com o motivo mostrado.
- **Traço (—) nos números**: o dado não existe no período. Não é zero.
- **Planilha simples tem menos informação**: é proposital; use o Export técnico para o detalhe.

Veja [OEE](topico:70-analises-oee) e [glossário](topico:05-glossario) para o significado dos indicadores.
