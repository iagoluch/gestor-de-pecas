# Plano do novo visual da gestão — 13/11/2026

Só apresentação. Regras, cálculos e dados do sistema ficam como estão.

## A ideia em uma frase

A tela passa a falar como um colega de fábrica: primeiro diz o que está acontecendo, depois mostra o número, e sempre explica o número.

## A identidade nova

- **Clara, não escura.** Gestão, Andon e Mapa passam a ter o mesmo fundo claro. Acaba o "pisca" de escuro para claro. (Responde ao problema 6.)
- **Vidro sutil.** Menu e cartões são levemente translúcidos sobre um fundo de cor suave (verde-água, azul-céu e pêssego bem claros). Borda com brilho fino. O texto fica sempre escuro sobre claro, então o vidro não atrapalha a leitura.
- **Cor só para estado de máquina.** Verde, azul, vermelho, amarelo, marrom, verde-água e cinza continuam com o significado de hoje. Botões e menu usam tinta escura, sem cor. Assim, o que é colorido na tela é sempre informação.
- **Letra de placa de fábrica** nos títulos e números (estilo DIN), letra comum no texto. Nada menor que 13. (Problema 4.)
- **A fita da fábrica.** No topo da Tela inicial, cada máquina é um quadradinho com a cor do seu estado. É a assinatura do novo visual: bate o olho e vê a fábrica inteira.

## Como cada problema da auditoria é respondido

1. **Números impossíveis** → o número acima do possível sai da vitrine e vira um aviso em "Precisa de você", dizendo a causa provável e onde corrigir.
2. **Número sem explicação** → todo número tem uma frase curta embaixo ("De cada 10 horas disponíveis, 6 viraram peça boa"). Colunas de tabela têm legenda no cabeçalho. Uma unidade só para tempo.
3. **Aviso técnico** → avisos reescritos: o que aconteceu + o que fazer. Sem nome de campo, sem inglês.
4. **Letra pequena** → mínimo 13, texto normal 15, números grandes.
5. **Vermelho para situação normal** → "Sem ordem na fila" fica cinza e tem um nome só. Vermelho fica reservado para parada não planejada.
6. **Telas diferentes entre si** → um só tema, uma só barra de filtros, busca sempre no mesmo lugar, um só botão "Exportar Excel", cartões sempre acima dos filtros.
7. **Lentidão** → a tela aparece inteira de uma vez com o que já tem e troca só o número que mudou. (A quantidade de consultas ao servidor é assunto de código, fica como recomendação à parte.)
8. **Telas menores** → tabelas com menos colunas (o resto abre ao clicar na linha); em tela estreita as colunas menos importantes somem em vez de cortar; no celular os números vêm antes dos filtros.
9. **Sim/Não como número** → vira frase: "Todas as contas têm responsável" ou "3 contas sem responsável".
10. **Excluir igual a Editar** → Excluir fica discreto e pede confirmação.
11. **Menu** → item vazio some; Pausas vai para o Admin; menu em 3 grupos: Acompanhar, Produção, Analisar.
12. **Teclado e clique** → foco sempre visível, menu escondido não recebe foco, alvo de clique com no mínimo 40.

## Movimento (só quando o dado muda)

- Número conta até o valor novo.
- Cartão da máquina troca de cor suavemente quando o estado muda.
- Evento novo entra no topo da lista.
- Cronômetro de parada corre.
- Linha da tabela acende por um instante quando avança.
- Nada gira, pulsa ou se mexe sem motivo. Quem pediu "reduzir animações" no computador vê a troca direta, sem movimento.

## Modo TV do Andon

- Sem vidro, sem embaçado, fundo liso.
- Sem menu, sem botão, sem nada flutuante.
- Só troca de cor e cronômetro. Feito para Chrome 79 e TV fraca.
- No protótipo: abrir com `?tv=1` no fim do endereço.

## O que este plano não faz

- Não muda cálculo de OEE nem regra nenhuma.
- Não mexe na bancada do operador.
- A fonte definitiva (estilo DIN) será embutida no sistema na hora de construir; o protótipo usa uma parecida que já vem no Windows.
