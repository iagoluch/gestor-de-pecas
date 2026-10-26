# Ranking de operadores e regressão à média

**Data:** 20/10/2026
**Projeto:** Gestor de Peças
**Origem:** conversa no OpenCode, iniciada com "Me surpreenda!"
**Assunto:** por que rankings de operador ou turno produzem melhoria fantasma, e o que fazer no lugar

---

## Resumo

Publicar ranking de operador ou turno medido com n pequeno cria melhoria que não existe: os piores melhoram e os melhores pioram por puro efeito estatístico, sem que nada mude no processo. O tamanho desse efeito é calculável, o teste que mede a confiabilidade do ranking cabe em vinte linhas, e a correção é shrinkage via modelo misto, não "mostrar o dado bruto".

---

## 1. A armadilha

Se você seleciona os piores 5 de qualquer lista medida com ruído e compara o desempenho deles no período seguinte, eles vão melhorar mesmo que nada mude no processo. O "ganho" esperado é (1 − confiabilidade) × distância da média. Com OEE por operador medido a uma confiabilidade de 0,6 (normal quando há poucas OP por pessoa), quem está 10 pontos abaixo da média sobe uns 4 pontos só por estatística. Quem está no topo cai o mesmo tanto. Os valores específicos para um caso concreto são estimativa; o fenômeno é aritmética, não opinião.

A consequência é tripla e acontece ao mesmo tempo:

1. O programa de melhoria recebe crédito por um ganho fantasma, e o próximo ciclo começa com a lição errada.
2. O operador que estava no fundo é treinado, cobrado ou punido por um número que era ruído.
3. O painel ensina todo mundo a otimizar o que aparece na tela, não o que acontece na máquina.

Correção proposta: nunca publicar média bruta de indivíduo com n pequeno. Estimar com shrinkage (empirical Bayes, puxando cada um em direção à média do grupo na proporção inversa da incerteza dele) e comparar cada operador com a própria linha de base, não com o colega. Ranking de turno só com mixed model que absorve mix de peça, senão o painel está ranqueando a programação da produção com sotaque de gestão de pessoas. O indicador que sobrevive a isso é tendência do grupo, não posição no pódio.

Verificação barata: pegar dois meses de qualquer métrica por operador e ver se o bottom 5 do mês 1 se repete no mês 2. Correlação baixa confirma que o ranking é ruído.

---

## 2. O mecanismo, em detalhe

### 2.1 O tamanho do fantasma é calculável

Se o desempenho verdadeiro varia entre pessoas com variância σ²_real, e a medição soma ruído σ²_erro, a confiabilidade é:

    ρ = σ²_real / (σ²_real + σ²_erro)

E a melhor previsão do desempenho verdadeiro de alguém, dado o número medido, é:

    verdadeiro_esperado = média + ρ × (medido − média)

ρ = 1 significa que o número é ouro. ρ = 0,5 significa que metade do desvio observado é ruído, e essa metade desaparece sozinha no período seguinte. É a conta inteira.

O detalhe cruel é que ρ depende de quantas observações a pessoa tem:

    ρ_n = n·ρ₁ / (1 + (n−1)·ρ₁)

Essa é a fórmula de Spearman-Brown. Quem fez 40 OPs tem estimativa decente; quem fez 6 tem estimativa quase inútil. E quem aparece no topo e no fundo do ranking tende a ser justamente quem tem menos dados, porque extremos são mais fáceis de atingir com pouco n. O ranking não é só ruidoso: ele é mais ruidoso exatamente onde se age.

### 2.2 O teste que encerra a discussão em vinte linhas

Não precisa de teoria. Pegar os eventos de cada operador, dividir aleatoriamente em duas metades, calcular a métrica em cada metade, ranquear as duas listas e medir a correlação de Spearman entre os rankings. Esse número é o teto de confiabilidade do ranking.

- Se der 0,2, o painel é um gerador de números aleatórios com paleta de cores.
- Se der 0,85, ranquear é legítimo e o problema é outro.

Usar metade aleatória e não mês 1 contra mês 2: assim se isola ruído de medição sem contaminar com mudança real de processo.

### 2.3 "Mostrar o dado bruto" também é uma escolha enviesada

O instinto de dizer "eu só mostro o número, sem interpretar" parece honesto, mas tem custo. O estimador não-viesado tem, no agregado, erro maior que um estimador deliberadamente encolhido em direção à média. É o paradoxo de Stein: com três ou mais grupos, encolher todos melhora o erro total sob perda quadrática, com a ressalva de que é um critério agregado, não uma garantia para cada indivíduo. Ou seja, shrinkage não é "suavizar para não machucar ninguém": é estatisticamente mais preciso. A versão empírica disso são os modelos mistos, com efeito aleatório por operador e efeito fixo para família de peça, turno e programação.

### 2.4 A armadilha da extração de boas práticas

Se o time estuda o turno campeão para descobrir o que ele faz de diferente, está estudando uma mistura de causa e sorte, e a parte sorte não é transferível. Pior: as práticas extraídas ficam enviesadas na direção do que quer que esteja correlacionado com sorte naquele período, e viram doutrina. O campeão seguinte é premiado por ter copiado um ritual. O antídoto é o mesmo: só extrair prática de diferença que sobreviveu ao split-half e ao ajuste de mix.

### 2.5 O custo de segundo grau: gaming

Métrica ruidosa publicada como ranking ensina a controlar a fonte do ruído, não o desempenho: recusar peça difícil, escolher OP curta, atrasar apontamento, reclassificar parada. As pessoas não são más, elas respondem ao sinal. Um número com ρ baixo é um convite para otimizar o número.

### 2.6 Se for mesmo necessário decidir sobre indivíduos

Aí é compra de dado, não de dashboard. Aumentar n por pessoa (janela maior, agrupar famílias similares), reduzir σ_erro com apontamento automático em vez de manual, ou aceitar que a decisão sobre indivíduo exige confiabilidade alta e que o custo disso é operacional. O que não funciona é multiplicar visões do mesmo dado ruidoso: três gráficos da mesma estimativa instável não somam informação nova.

---

## 3. A pergunta de produto

O painel existe para comparar pessoas ou para detectar mudança? São métricas diferentes, com desenhos diferentes. Escolher as duas ao mesmo tempo é o que produz o pódio que pune o azarado.

---

## 4. Próximo passo sugerido

Rodar o teste de split-half sobre o indicador real do Gestor de Peças, com `oee-engineer` (métrica e modelo) e `database-engineer` (extração dos eventos e variância). O entregável é o ρ do indicador, o único número dessa análise que não pode ser estimado de cabeça.
