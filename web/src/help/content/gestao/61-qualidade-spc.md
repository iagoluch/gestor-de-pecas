---
titulo: Qualidade - SPC
grupo: Qualidade
ordem: 61
rotas: /qualidade/spc
---

A tela **Qualidade — SPC** mostra se as medidas das peças estão estáveis ao longo do tempo. SPC quer dizer controle estatístico do processo. Aqui é **só consulta**: nada é gravado e os números já chegam calculados do servidor.

Texto da tela: "Cartas de controle e Cpk das cotas já medidas. Somente consulta: os números vêm prontos do servidor."

## Quem pode ver

Só **Qualidade** e **Admin**. Os outros níveis recebem "Seu perfil não tem acesso ao SPC. Só a Qualidade e a administração usam esta tela."

## Filtros

| Campo | Como funciona |
|---|---|
| Produto | Código do produto. |
| Cota | Número da cota (1 a 200). |
| De / Até | Período das medições (dia inteiro). |
| Limpar filtros | Zera tudo. |

Ao lado aparece o total de séries encontradas.

## O que é uma "série"

Cada cartão da tela é uma série: **um produto + uma cota + uma revisão do padrão**. Revisões diferentes do padrão nunca se misturam.

Peças reprovadas **também entram**. A Qualidade mede todas as peças da OP, e tirar as ruins esconderia justamente a variação que o SPC precisa mostrar.

## Avisos no topo

- "Cada série precisa de pelo menos 20 medidas e 5 subgrupos para ter limites de controle e Cpk."
- "Há medições demais para o filtro: só as mais recentes foram analisadas. Use produto, cota ou período para reduzir." (o servidor analisa no máximo 20.000 medidas).
- "Medidas fora da análise: N de cota com padrão não numérico e N com valor inválido."

## Dentro de cada cartão

| Campo | Significado |
|---|---|
| Título | Produto e cota (com descrição, se houver). |
| Medidas / subgrupos | Quantas medidas e quantos grupos entraram. |
| Padrão da cota | O padrão exatamente como estava na época da medição. |
| Especificação | Limite mínimo a limite máximo da peça (padrão menos e mais a tolerância), em mm. |
| Tipo de carta | Veja abaixo. |
| Cpk | Nota da capacidade. Se não der para calcular, o motivo aparece no lugar do número. |
| Cpk superior (CPU) | Nota considerando só o limite máximo. |
| Cpk inferior (CPL) | Nota considerando só o limite mínimo. |

O Cpk é o menor entre CPU e CPL. Fórmulas: CPU = (limite máximo − média) ÷ (3 × variação); CPL = (média − limite mínimo) ÷ (3 × variação). Exemplo: média 125,1, limites 124,5 e 125,5, variação 0,1. CPU = 0,4 ÷ 0,3 = 1,33. CPL = 0,6 ÷ 0,3 = 2,0. Cpk = 1,33.

Como ler: quanto maior, melhor. Valores abaixo de 1 indicam que o processo tende a sair da tolerância. Os valores de referência da empresa: confirmar com a liderança.

Abaixo do número há sempre um rótulo. Na carta X-barra e R: "Cpk dentro da OP/lote (variação curta); não é a capacidade da máquina." Ou seja, o Cpk mede a variação dentro de uma mesma OP. Na carta de valores individuais: "Cpk de curto prazo entre peças consecutivas (pode cruzar OPs); não é a capacidade da máquina." Nos dois casos não é a capacidade total da máquina.

### Tipo de carta

| Tipo | Quando | O que cada ponto é |
|---|---|---|
| X-barra e R | Quando o grupo típico (a mediana dos grupos) tem 2 ou mais peças | Um grupo de peças da mesma OP: média e amplitude (maior menos menor). |
| Valores individuais e amplitude móvel | Quando o grupo típico tem só 1 peça (em geral, 1 peça por OP) | Cada medida é um ponto; a amplitude é a diferença para a peça anterior. |

Regras do sistema para os grupos: inspeção com mais de 10 peças é cortada em blocos de 5 (se sobrar 1 peça, ela vai para o bloco anterior). Na carta X-barra e R, grupos de 1 peça ficam fora; a tela avisa "N subgrupo(s) de 1 peça ficaram fora da carta."

## Os dois gráficos

Cada cartão tem dois gráficos: um com as **médias** (ou valores individuais) e outro com a **dispersão** (amplitudes). Passe o mouse num ponto para ver: número do ponto, OP, quantidade de peças, data, valor e sinal.

Linhas: **LSC** (limite superior de controle), **LC** (linha central) e **LIC** (limite inferior de controle). Os limites vêm do comportamento real do processo, não da tolerância do desenho.

### Sinais de alerta (cores/marcas)

| Marca | Significado |
|---|---|
| Ponto normal | Dentro dos limites. |
| Fora dos limites | O ponto passou do LSC ou ficou abaixo do LIC. |
| Sequência de 7 do mesmo lado | Sete pontos seguidos acima (ou abaixo) da linha central: o processo andou para um lado. |

Embaixo: "N ponto(s) com sinal nesta série." ou "Nenhum ponto com sinal nesta série."

## Quando não há limites ou Cpk

| Mensagem | Motivo |
|---|---|
| Amostra insuficiente: N medidas em N subgrupos (mínimo 20 medidas e 5 subgrupos). | Poucos dados. O gráfico aparece como tendência, sem limites e sem Cpk. |
| Sem variação dentro dos subgrupos (a resolução da medição não mostra diferença entre peças da mesma OP): limites de controle não calculados. | Todas as peças de cada OP tiveram a mesma medida. |
| Padrão sem tolerância (margem zero): Cpk não se aplica. | Cota sem tolerância. |
| Cpk indisponível / Não calculado | Não deu para calcular. |

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| Sem medições suficientes (com filtro: Nenhuma cota medida neste filtro...) | Confira produto, cota e período, ou limpe os filtros. |
| Sem medições suficientes (sem filtro: Ainda não há cotas medidas pela Qualidade...) | Ainda não houve inspeção com medidas. |
| O período informado é inválido. Confira as datas. | Corrija De/Até. |
| Algum filtro está inválido. Confira o produto, a cota e as datas. | Revise os campos. |
| Não foi possível carregar o SPC. Tente novamente. | Clique em **Tentar novamente**. |

Veja também: [Cotas padrão](topico:60-qualidade-cotas).
