---
titulo: Diretoria
grupo: Diretoria
ordem: 66
rotas: /diretoria
acesso: diretoria
---

A tela **Diretoria** responde, em poucos números: "Quanto produzimos, onde perdemos tempo e quanto isso custou." Os números de horas, peças e eficiência são os **mesmos da Visão Geral**. O que a Diretoria acrescenta é o custo em reais (R$).

Esta tela contém valores de custo e é sensível. Só aparece para **Admin** e **Diretoria**. Para os outros níveis a seção some do menu e o endereço volta para outra tela. Os valores em reais só saem por uma rota exclusiva desses dois níveis.

## Como a tela é organizada

No alto há dois grupos de botões.

| Grupo | Opções |
|---|---|
| O que ver | **Painel**, **Ficha**, **Custos** |
| Período (não aparece em Custos) | **Hoje**, **Semana**, **Mês** |

- **Hoje**: o dia de hoje inteiro.
- **Semana**: de segunda-feira até hoje.
- **Mês**: do dia 1º até hoje.

Os períodos são os mesmos recortes da Visão Geral.

## Aba Painel

### Quatro cartões

| Cartão | O que significa |
|---|---|
| Produzido | Peças boas lançadas no período. |
| Horas paradas | Tempo parado **não planejado** (paradas planejadas não entram). Conta igual à Visão Geral: tempo de parada menos a parada planejada; parada sem classificação também conta. |
| Custo das paradas | Horas paradas × valor da hora. Veja "Como o custo é calculado". |
| Eficiência | "Quanto do tempo virou peça boa", o mesmo OEE da Visão Geral. Veja [Análises — OEE](topico:70-analises-oee). |

Todo número desses cartões é clicável. Ao clicar abre um painel lateral com a **conta aberta**: de onde vem o número, passo a passo.

Avisos que podem aparecer:

- "faltam custos de N recursos/pessoas — o valor real é maior": há máquina ou pessoa sem valor da hora cadastrado. O custo mostrado é parcial. Se nenhum valor estiver cadastrado, o cartão mostra **Sem custo cadastrado** (não "R$ 0").
- "Eficiência acima de 100%: as peças saíram mais rápido que o tempo padrão cadastrado. O número é real (não foi limitado); vale revisar o tempo padrão do produto."

### Onde mais perdemos

Lista numerada (1º, 2º, 3º) com os **três setores** que mais ficaram parados. Cada linha mostra:

- o nome do setor e o **principal motivo** de parada (ou "Motivo não informado");
- as horas paradas e o custo (com "(parcial)" quando faltam valores).

Clique no nome do setor para abrir a **Ficha** dele. A linha "Sem setor" não abre ficha. Se não há paradas: "Sem paradas no período".

### Melhor e pior setor

| Cartão | Significado |
|---|---|
| Setor que melhor aproveitou o tempo | Setor com a maior eficiência (OEE) no período. |
| Setor que mais desperdiçou tempo | Setor com a menor eficiência. Não aparece se só um setor teve dados ou se houve empate total. |

Textos vazios: "Sem dados de eficiência por setor no período." e "Só um setor teve dados no período." Se a eficiência passa de 100% aparece "Acima de 100%: confira o tempo padrão deste setor."

## Aba Ficha

A ficha é um resumo de um recorte (a fábrica toda, um setor ou uma máquina).

| Filtro | Como funciona |
|---|---|
| Setor | "Todos os setores" ou um setor. Mudar o setor zera o recurso. |
| Recurso | "Todos os recursos" ou uma máquina/posto (a lista respeita o setor). |

Setores e recursos vêm do mesmo cadastro da aba Custos.

No topo há uma **frase pronta**, por exemplo: "Dobra trabalhou 20 h de 24 h e produziu 300 peças. Ficou parado 3 h, o que custou R$ 450. Principal motivo: Falta de material (2 h)." Se faltar valor da hora, a frase termina com "Atenção: faltam custos de N recursos/pessoas — o valor real é maior."

### Cinco cartões

| Cartão | Significado |
|---|---|
| Trabalhou | Horas trabalhadas, "de N h disponíveis no turno". |
| Produzido | Peças boas lançadas. |
| Parado | Horas paradas não planejadas, com o principal motivo. |
| Custo do trabalho | Horas trabalhadas × valor da hora. |
| Custo das paradas | Horas paradas × valor da hora. |

Quando faltam valores: "Valor parcial: faltam N valor(es) da hora". E uma faixa avisa "Faltam custos de N recursos/pessoas — o valor real é maior."

### Listas da ficha

| Lista | Conteúdo |
|---|---|
| Paradas por motivo | Cada motivo com suas horas (clicável). "Nenhuma parada fora do planejado" se vazio. |
| Quem operou | Cada operador com horas e custo. "Ninguém apontou trabalho neste período" se vazio. |
| Tempo que não entra no custo | **Sem demanda** (recurso sem serviço) e **Fora do turno** (fora do horário de trabalho). Essas horas não contam como parada. |

## Aba Custos

Aqui se cadastra o **valor da hora em R$** de cada máquina/posto e de cada pessoa. Esse valor alimenta todos os custos da tela.

1. Abra **Custos**.
2. Ache o recurso (em "Recursos (máquinas e postos)") ou a pessoa (em "Pessoas (operadores)").
3. Digite o valor no campo "R$ ... /h", por exemplo 12,50.
4. Clique em **Salvar**. Aparece "Salvo."

O valor já cadastrado aparece como "Cadastrado: R$ 12,50/h" e também abre a conta ao clicar. Quem fica sem valor aparece como "sem custo cadastrado" nos cálculos. Esta aba não tem filtro de período e não atualiza sozinha enquanto você digita.

Regras do valor: maior que zero, até 2 casas decimais, abaixo de 10 bilhões. Aceita "12,50", "1.250,75" ou "12.5". Cada alteração fica registrada (quem mudou, quando, antes e depois).

## Como o custo é calculado

Para cada trecho de tempo: **horas × (valor da hora da máquina + soma do valor da hora de cada pessoa que estava alocada no trecho)**. Quem não tem valor conta como R$ 0 e o resultado vira "parcial".

Exemplo: máquina R$ 100/h, duas pessoas de R$ 20/h, parada de 2 horas. Custo = 2 × (100 + 20 + 20) = R$ 280.

Paradas simultâneas com motivos diferentes na mesma máquina não são contadas em dobro. O trecho fica com a parada que começou primeiro.

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| Valor inválido. Digite o valor da hora em reais, maior que zero, por exemplo 12,50. | Corrija o valor (sem espaços, sem negativo, sem zero). |
| O valor por hora precisa ser maior que zero (até 2 casas) e menor que 10 bilhões. | Mesma coisa; a regra vem do servidor. |
| Operador não encontrado. | A pessoa não existe mais no cadastro; recarregue a tela. |
| Período inválido: use hoje, semana ou mes. | Escolha um dos três botões de período. |
| Você não tem acesso a esta explicação. | Só Admin e Diretoria abrem a conta aberta. |
| Não foi possível carregar a explicação agora. | Clique em **Tentar novamente**. |
| Sem custo cadastrado | Falta valor da hora; cadastre na aba Custos. |
| Nenhum recurso cadastrado / Nenhum operador cadastrado | Os cadastros de base (recursos e operadores) estão vazios. Peça ao Admin para conferir o Cadastro. |

Todo valor da hora alterado fica registrado (quem mudou, quando, antes e depois). Esse registro de custos **não aparece em nenhuma tela**: só pode ser consultado por uma rota técnica do sistema, restrita a Admin e Diretoria. A tela **Alterações** (só Admin) não mostra valores em reais. Para conferir uma mudança feita por engano, peça ao Admin.
