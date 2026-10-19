# Todo número clicável e explicado — desenho

Data: 16/10/2026 · Origem: conversa com Iago · Status: **aguardando aprovação** (nada foi construído)

## 1. Por que isso existe

Hoje o Gestor mostra números sem dizer de onde vêm. Exemplo real que disparou o pedido: na Visão Geral, "Recurso sem demanda 509,6 h, média 13,4 h (38 recursos)". Um funcionário, ou a diretoria, pergunta "de onde vêm essas 500 horas?" e o sistema não responde. A "IA Industrial" também não respondeu: ela só recebe totais.

Regra pedida pelo Iago, vale para o sistema inteiro: **todo número, indicador ou status mostrado (horas, peças boas, refugo, retrabalho, OEE, percentuais, contagens) é clicável e abre uma explicação com os valores reais, do total até o registro bruto: por que está assim, de onde veio, quem gerou.** Uma divisão ("510 h ÷ 38") não basta, porque gera a pergunta seguinte. A explicação tem que listar o que compõe o total e a lista tem que fechar com ele.

## 2. Objetivos, não-objetivos, anti-objetivos

**Objetivos**
- Clicar em um número abre um painel com: o número, uma frase de motivo, e a composição (setor → recurso → trecho), com a conta fechando em linha visível.
- A mesma regra para tempo, peças boas, refugo e retrabalho, e depois para o restante do inventário (ver seção 6).
- A mesma conta em todas as telas: o mesmo nome nunca mais mostra dois números.

**Não-objetivos**
- Não mudar o fluxo do operador nem criar atrito no chão de fábrica.
- Não pôr botões em telas de TV (Andon e Solda).
- Não reconstruir histórico que não foi gravado.

**Anti-objetivos** (seria fracasso mesmo funcionando)
- O funcionário ter que passar de tela em tela. É um painel só, que se expande por dentro.
- O painel ficar denso. Pedido explícito: quanto mais simples de visualizar, melhor.
- Um número explicado que não bate com o número clicado.

## 3. Decisões do Iago (valem como regra)

1. **Painel único e simples.** Número grande no topo, uma frase de motivo, barras por setor. Clicar numa barra abre o recurso e depois os trechos, ali mesmo. Ao fim, uma linha confirma que a soma bate. O registro técnico (id, origem) só aparece ao clicar num trecho. Mockup aprovado: `.superpowers/brainstorm/8930-1792171523/content/explicacao-simples.html`.
2. **Média por recurso** = total ÷ recursos que tinham turno/calendário no período, em todas as telas. Sempre mostrar "N recursos".
3. **Parada** nunca aparece solta. Sempre duas linhas, "Parada planejada" e "Parada não planejada", e o total é a soma das duas, em todas as telas.
4. **Sem demanda não precisa começar a ser gravado.** Ele já é gravado como trecho com recurso, início, motivo, quem e origem (confirmado em `app/database/database.py`, `_entrar_sem_demanda_tx` e o INSERT em `eventos_estado_recurso`). Vale também para dias passados.

5. **Sem abas e sub-abas novas.** A explicação abre como **painel lateral que desliza por cima da tela** (pop-up), ao clicar em qualquer número. O menu do sistema não ganha nada. Dentro do mesmo painel, embaixo da explicação, fica um **chat com a IA** para o funcionário digitar perguntas que a explicação não respondeu.

## 3.1 O chat dentro do painel (decisão do Iago + escolhas do desenhista)

- A IA do chat recebe **a mesma explicação que o funcionário está vendo** (número, composição, trechos, o que ficou de fora, a regra), não só o total. Esta é a correção do problema original: a IA Industrial "horrível" respondia sem enxergar de onde vinha o número.
- Escolha do desenhista: a IA responde **somente com base no que recebeu**. Se a pergunta foge disso, ela diz que não sabe e aponta a tela existente (ex.: Rastreabilidade da OP). Ela não inventa causa.
- Escolha do desenhista: se a explicação foi cortada por tamanho, a IA avisa isso na resposta em vez de fingir que viu tudo.
- O chat entra **já na Fase 1**, junto com o painel. Dono técnico: `ai-llm-engineer`.
- Em TV (Andon, Solda) não há clique nem painel.

## 4. O que cada nível do painel mostra

- **Topo:** o número, a média e o total do turno, e a que ele pertence (ex.: sem demanda é parte do tempo do turno, junto de produção, setup e parada).
- **Frase de motivo:** uma linha em português simples com a regra e a causa do dia (ex.: "Nenhuma OP foi apontada hoje nestes recursos"). Quando existir, a última OP encerrada no recurso e por quem.
- **Barras:** setor → recurso → trecho (hora de início e fim, duração, quem gerou, origem). Trechos que ficaram de fora e o motivo (ex.: intervalo de almoço = parada planejada) aparecem em uma linha apagada.
- **Fechamento:** "✓ os setores somam X, igual ao número clicado". Se não bater, aviso vermelho com a diferença.
- **Horário:** "calculado às HH:MM", porque o dia ainda está em andamento.

Peças boas, refugo e retrabalho usam o mesmo molde, mas a lista é de lançamentos (hora, OP, recurso, quantidade, motivo, quem lançou). Cada linha leva à Rastreabilidade da OP, que já existe.

## 5. O que o inventário achou que impede isso hoje

Levantamento de 82 números (agente de varredura, 16/10/2026; itens marcados "suposição" no arquivo não foram conferidos no código). Arquivo no repositório: `docs/superpowers/specs/2026-10-16-explicacao-clicavel-inventario.md`.

Problemas que o painel vai expor e que precisam virar uma regra única:
1. **Perda de origem na soma.** `consolidate_physical_time` perde o `source_ref`; conflitos viram "a esclarecer" e paradas de classes diferentes viram "não planejada". Para o painel fechar com o total, a soma precisa carregar os ids dos eventos que a formaram e a regra aplicada.
2. **Média com três divisores** (nº de recursos da lista, recursos com calendário, outro no overview). Resolvido pela decisão 2.
3. **"Parada" com quatro definições** (consolidado, consolidado menos planejada na Diretoria, soma da lista de eventos, arredondamentos diferentes "26h36m" e "26,6 h"). Resolvido pela decisão 3, mas a lista de eventos de Análises > Paradas precisa passar a bater com o consolidado.
4. **Cartões somados no navegador sobre 200 linhas** (Produção > OPs, Planejado x Realizado, Operações > Ordens) enquanto "Ordens no filtro" usa o total real. Acima de 200 OPs subcontam em silêncio. Decisão do desenhista: os totais passam a vir da API.
5. **Exclusões silenciosas** (padrão x real só soma linhas com esperado e real; Andon corta em 6 OPs; pendentes de inspeção olham só 1000 OPs; listas da IA cortam em 50/12/100). O painel deve dizer o que ficou de fora.
6. **Só 4 cartões (OEE, Disponibilidade, Performance, FTT) têm explicação clicável hoje** (`ManagementInsightDrawer`, `management_insights.py`). O restante não tem identificador estável de métrica nem lista de itens que compõem.

## 6. Como construir, em linhas gerais (escolhas do desenhista)

Estas são minhas escolhas, não decisões do Iago. Podem mudar no plano.

- **Um mecanismo genérico**, não uma tela por número: cada métrica ganha um identificador estável (ex.: `tempo.sem_demanda`, `tempo.parada_planejada`, `pecas.refugo`) e um endpoint "explicação da métrica" que recebe métrica + filtro/período e devolve a árvore (total, filhos, trechos/lançamentos, itens excluídos com motivo, regra em frase, hora do cálculo). O componente de painel no frontend é um só.
- **A explicação nasce da mesma conta que gera o número**, não de uma segunda conta. Isso evita duas fontes de verdade divergentes. O mesmo conteúdo alimenta a IA Industrial (que hoje só vê totais).
- **A Fase 1 só explica; não muda fórmula.** OEE, custo da Diretoria e digest do Telegram continuam com a conta de hoje. O que muda é o rótulo e a apresentação (decisões 2 e 3). Se a explicação revelar que uma conta existente está errada, isso vira achado a decidir com o Iago, não correção silenciosa.
- **Tempo "a esclarecer"** (conflitos que o sistema não soube classificar) aparece como **terceira linha própria**, ao lado de Parada planejada e não planejada, nunca escondido dentro de uma delas. Com a explicação dos intervalos em conflito.
- **Quando a lista de eventos (Análises > Paradas) não bate com o consolidado, vale o consolidado**: é o número em que o usuário clicou. A lista ganha uma linha "diferença: X h, motivo: …" até ser reconciliada.
- **Média em vários dias:** divisor = recursos distintos que tiveram turno/calendário em algum dia do período. O painel mostra "N recursos, D dias" para não haver dúvida.
- **Quem vê o quê:** o painel respeita a permissão da tela onde o número está. Nome/crachá de quem gerou só para níveis de gestão; custo só para quem já vê a Diretoria; operador não ganha clique nas telas de operador (nenhum atrito novo). O endpoint de explicação valida o nível no servidor.
- **Custo da Diretoria em dias passados** usa a taxa de hoje, com aviso visível no painel ("taxa atual, sem histórico"). Versionar a taxa por vigência fica para depois, só se o Iago pedir.
- **Fases, da mais barata para a mais cara:**
  1. Tempo: sem demanda, parada planejada e não planejada, média, categorias de tempo (Visão Geral e Operações > Tempo), mais o painel lateral genérico e o chat com a IA. Inclui carregar `source_ref` no consolidado.
  2. Peças boas, refugo, retrabalho (Produção, Qualidade, Visão Geral). Inclui trocar as somas de 200 linhas por totais da API.
  3. Cartões OEE e demais KPIs, Diretoria (custo), Corte, tempo padrão, integrações — migrando para o mesmo molde.
- **Classificação de risco:** R3. Toca regra industrial (consolidação de tempo físico, OEE). Exige owner de domínio (mes-domain-guardian / oee-engineer), QA e revisão independente. Cada fase fecha com o teste "a lista soma o total".
- **Telas de TV:** sem botão de clique. Andon e Solda ficam como estão.
- O trabalho em andamento no repositório (aba Diretoria, fila manual por área) não deve ser tocado.

## 7. O que ainda é decisão do Iago

Não bloqueiam a Fase 1 (tempo + painel + chat). Bloqueiam a Fase 2 (peças) e podem ser respondidas depois:
1. **Base do percentual.** Na Produção, "% do planejado" no cartão conta só peças boas; "% atendida" na tabela conta boas + refugo; o saldo ignora retrabalho; "refugo %" não inclui retrabalho, mas o FTT inclui. Qual é a conta única para cada nome?
2. **"Aguardando inspeção".** Existem duas contagens diferentes (peças das inspeções abertas × OPs elegíveis com limite de 1000). Qual vale?
3. **Ordem das fases.** Proposta: 1 tempo, 2 peças, 3 o resto. Confirma?

## 8. Pontos não conferidos

Estado após a Fase 1 (16/10/2026):

- **Resolvido:** `NO_DEMAND` vem só dos estados `fila` gravados sem OP; os trechos são listados por evento. Confirmado e coberto por teste.
- **Resolvido:** a Fase 1 não precisa de snapshot histórico da fila (os eventos bastam).
- **Aberto (Fase 2/3):** itens do inventário marcados "suposição": Telegram digest, Metas, fila manual por área, tela de Corte e Destaque, auditoria.
- **Aberto (Fase 3):** o custo da Diretoria usa a taxa de hora atual (suposição); se não houver vigência, a explicação de custo de dias passados usaria a taxa de hoje.
- **Novo, aguardando o Iago:** (a) a média usa só recursos com calendário, mas o total inclui o tempo de recursos sem calendário; a árvore avisa nas notas; (b) a planilha executiva ganhou uma linha "A esclarecer" quando > 0; (c) "Parada não planejada" tem duas contas (cartão/painel = total − planejada; `_perdas_canonicas` = só a classificação não planejada), que diferem só em paradas sem classificação; (d) a linha "Desconhecido" em Operações > Tempo não é clicável e pode divergir de "A esclarecer"; (e) o nome do operador segue para o provedor externo de IA (consistente com o desenho, só registrar).
- **Fase 2:** Operações > Tempo mistura duas fontes (`physical_inputs` e `physical_consolidation`); unificar. Extrair `_fit_level`/`_truncate`/`_count` de `metric_explanation.py` para módulo próprio.

## 9. Decisões de 19/10/2026 (respostas do Iago às cinco perguntas da fase 1)

- **Parada não planejada = parada total − planejada**, em todo lugar (cartão, composição, explicação, planilha). Aplicado em `ManagementService` (fonte única). Inclui a parada ainda sem classificação.
- **Linha "A esclarecer"** (`conflicting_state_seconds`) na planilha executiva de perdas, só quando maior que zero. Aplicado em `_perdas_canonicas` e `build_perdas`.
- **"Desconhecido" em Operações > Tempo continua sem clique.** Nenhuma mudança.
- **Nome do operador para o provedor de IA externo** (painel só da gestão): aceito pelo Iago. Registrado aqui como decisão consciente.
- **Média e total de horas só com recursos que têm turno (opção 1A): APLICADA na opção (b), só na explicação e no cartão "Composição do tempo".** Filtrar na consolidação compartilhada zerava OEE, indicadores por recurso e a ficha de custo da Diretoria (16 testes quebrados), então o recorte é feito à parte: `restrict_to_resources` (`mes/analytics/physical_time.py`) usado por `MetricExplanationService.explain` e por `ManagementService._calendar_scope` (chave aditiva `hours.calendar_scope`, lida só por `FrontendBackendFacade.inicio()`). `_consolidate_physical`, OEE, KPIs por recurso e Diretoria seguem contando todos os recursos, então o total do cartão pode diferir dessas telas. A árvore e o cartão avisam "N recurso(s) sem turno cadastrado, <tempo>, ficam fora do total e da média". Fora do turno nunca é recortado (é número de calendário). Nesting legado sem horário entra se o recurso tem turno, mesmo sem trecho consolidado. **Sem nenhum calendário cadastrado (caso do REAL hoje) a regra não se aplica:** o total fica inteiro e só a média some, como antes.
