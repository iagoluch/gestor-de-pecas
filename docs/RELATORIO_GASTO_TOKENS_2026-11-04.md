# Relatório: o que mais gasta seu uso do Claude (04/11/2026)

Plano Pro. Hoje: limite de 5 horas em **98%**, semanal em **40%**.
Fonte: transcrições em `~/.claude/projects` (sessões ativas desde 28/10), `get_usage`, tamanho dos arquivos de configuração.
Limite da análise: contei tokens, não o custo exato da cota. Opus pesa mais por token que Sonnet, então o Opus pesa mais do que os números mostram.

## Resumo em uma frase

Você não gasta por pedir muito. Gasta porque **cada resposta relê uma conversa enorme** (média de 141 mil tokens por chamada) e ~89 mil desses tokens são fixos, antes de você escrever qualquer coisa.

## 1. Conversas longas demais (maior causa)

Evidência:
- Desde 29/10, a sessão principal relê em média **141 mil tokens por chamada** (5.962 chamadas). Subagentes: 82 mil (1.740 chamadas).
- Total lido do cache nas sessões recentes: **3,5 bilhões de tokens** em 28 mil chamadas. Saída (o que o modelo escreve) é só ~22 milhões. Ou seja, o custo é quase todo releitura.
- As 4 maiores sessões têm 2.300 a 3.450 chamadas cada e 330 a 450 milhões de tokens relidos cada. Os arquivos delas têm 50 a 137 MB.
- Dias pesados: 29/10 (3.021 chamadas), 03/11 (2.061), 24/09 e 25/09 (~2.400 cada).

Por que gasta: cada mensagem nova paga de novo todo o histórico. Conversa de 3.000 chamadas custa muito mais que 10 conversas de 300.

Como resolver:
1. Uma sessão por tarefa. Terminou a tarefa, abra sessão nova (ou use `/clear`).
2. Compacte ao chegar perto de 60% do contexto, não de 84%.
3. Não deixe a mesma sessão aberta por dias.

## 2. Peso fixo de cada conversa: ~89 mil tokens antes da sua primeira palavra

Medido agora nesta sessão (143 mil usados no total):

| Parte | Tokens |
|---|---|
| Ferramentas do sistema | 32.900 |
| Ferramentas de MCP (servidores extras) | 19.000 |
| Arquivos de memória (CLAUDE.md + índice) | 17.600 |
| Instruções do sistema | 10.300 |
| Skills | 10.000 |
| Suas mensagens | 48.500 |

Esse bloco é relido em **toda** chamada. 89 mil × 5.962 chamadas = mais de 500 milhões de tokens só de peso fixo.

Evidência extra:
- `~/.claude/CLAUDE.md` tem **35 KB** (~9 mil tokens). A maior parte é regra repetida (handoff Nemotron, GLM, Haiku, validação, eficiência dita 3 vezes).
- 23 agentes globais (26 KB) e 45 skills instaladas; a lista deles entra no contexto.
- Servidores MCP ligados: rea (centenas de ferramentas de engenharia reversa), github, computer-use, browser, chrome, context-mode, headroom. Só as ferramentas de MCP somam 19 mil.

Como resolver:
1. Encurtar o CLAUDE.md global para ~8 KB (regras curtas; detalhes em arquivo lido só quando preciso). Ganho estimado: ~6 mil tokens por chamada.
2. Desligar MCPs que você não usa no dia a dia (rea, github, computer-use) e ligar só quando precisar. Ganho: até ~10 mil por chamada.
3. Tirar skills e agentes sem uso (já houve quarentena em 29/09; vale repetir).
4. Meta realista: de 89 mil para ~55 mil fixos.

## 3. Opus em muitas chamadas

Evidência (sessões desde 28/10):
- Opus 5.5: **10.704 chamadas** (38% do total), 1,3 bilhão de tokens relidos, 8,6 milhões escritos.
- Sonnet 5.5: 13.886 chamadas. Haiku: 1.326.

Por que gasta: Opus consome a cota bem mais rápido por token. Tarefa mecânica (ler arquivo, rodar teste, editar texto) não precisa dele.

Como resolver:
1. Padrão = Sonnet. Opus só para decisão difícil, bug de causa desconhecida e revisão final.
2. Já feito hoje: Opus com esforço médio no orquestrador e no modelo-auto (ainda precisa reiniciar o Desktop).

## 4. Capturas de tela lidas como imagem

Evidência:
- Ferramentas `Read` devolveram **7,9 MB** em 541 leituras desde 29/10. As maiores são imagens PNG de 200 a 533 KB (`d3_analises_qualidade.png`, `explore_robo1.png`, etc.).
- Navegador embutido: 662 chamadas de `computer` + 188 de `browser_batch`, ~2 MB de resultado.
- Bash: 3,5 MB em 1.736 chamadas.

Por que gasta: imagem grande entra inteira no contexto e fica lá, sendo relida em todas as chamadas seguintes.

Como resolver:
1. Prova visual: salvar a imagem em disco e olhar uma vez; depois não reler.
2. Para checar texto de tela, usar `get_page_text`/`read_page` (texto, barato) em vez de screenshot.
3. Reduzir tamanho das imagens (zoom na região, `scale` menor).

## 5. Cache que se perde e é recriado

Evidência: **539 chamadas** com recriação de cache acima de 60 mil tokens em 4 dias (162 em 29/10, 107 em 30/10, 209 em 03/11, 61 hoje). Recriar custa 1,25× o contexto inteiro.

Por que acontece: pausa longa entre mensagens, ou mudança no começo do contexto (reinício de servidor MCP, hook que muda texto, troca de modelo no meio da sessão).

Como resolver:
1. Não trocar de modelo no meio de uma sessão longa.
2. Não deixar sessão parada e voltar depois: abrir sessão nova com resumo curto.
3. Manter MCPs estáveis (o context-mode e o headroom falharam ao abrir hoje e podem ter forçado recriação).

## 6. Itens menores

- `update_plan` (402 chamadas) e `wrap_up` (218): exigidos pelo app; cada um é uma chamada completa relendo ~140 mil. São ~8% das chamadas. Só reduzem se a tarefa for pequena (o app já dispensa em pergunta simples).
- Subagentes: 1.740 chamadas, 116 aberturas de `Agent`. Cada subagente começa com ~80 mil de peso. Vale só quando o trabalho é realmente independente.
- Hooks de sessão: o aviso do context-mode ao abrir a sessão tem ~29 KB, e é repetido a cada compactação. O hook de roteamento por mensagem é pequeno (615 bytes).

## Plano de ação, em ordem de ganho

1. **Hoje:** abrir sessão nova para a próxima tarefa e fechar esta (já compactada, 72% cheia).
2. **Esta semana:** encurtar o CLAUDE.md global de 35 KB para ~8 KB. Posso fazer com sua confirmação (guardo backup).
3. **Esta semana:** desligar os MCPs rea, github e computer-use por padrão.
4. **Rotina:** Sonnet como padrão; Opus só quando precisar; screenshots só quando for prova.
5. **Depois de 1 a 3 dias:** comparar o `get_usage` para ver se o limite de 5 horas deixou de chegar a ~100%.

## O que eu não consegui provar

- O quanto de cota cada modelo consome por token (a Anthropic não expõe a fórmula). Por isso o item 3 é ordem de grandeza, não número exato.
- Quanto de cada MCP é realmente usado por dia: contei chamadas (rea e github quase não aparecem), mas não medi um mês inteiro.
