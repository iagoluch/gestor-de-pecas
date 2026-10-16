# Aba "Diretoria" na tela de gestão — design

Data: 2026-10-16. Pedido do Ezequiel (diretoria), relatado pelo Iago (admin).

## Intenção e por quê

A diretoria (a Sra. Gilvana e o Ezequiel) não tem tempo nem paciência para
montar a resposta a partir de várias telas. Perguntas típicas: "o que o recurso
X fez no setor Y, em quanto tempo, quanto custou, por que ficou parado?".
Eles querem **respostas prontas e resumidas**, em uma aba só deles.

Hoje o sistema já tem tempo trabalhado, paradas com motivo, produção, equipe e
OEE, mas **não tem nenhum valor em reais**. Sem custo a aba não responde a
pergunta central ("quanto custou"). Por isso o projeto inclui o cadastro de
custo por hora.

Sucesso = a diretoria abre a aba, escolhe no máximo 3 filtros e lê a resposta
em uma ou duas frases, sem precisar interpretar gráfico ou cruzar tela.
Se funcionar bem para a diretoria, o mesmo desenho será estendido aos outros
níveis depois (ver "Fora de escopo").

## Metas

1. Nova aba **Diretoria** na tela de gestão, visível só para os níveis
   `diretoria` e `admin`.
2. **Painel** (visão geral do período): produzido, horas paradas, custo da
   parada, eficiência (OEE); os 3 setores onde mais se perde (horas, R$ e
   motivo principal), com clique para abrir a ficha; destaque do melhor e do
   pior setor.
3. **Ficha por setor/recurso**: filtros Setor, Recurso, Período; um parágrafo
   pronto em português ("O LASER1 (Corte) trabalhou 31 h de 40 h e produziu
   128 peças. Ficou parado 9 h, o que custou R$ 2.250. Principal motivo:
   falta de material (5 h)"), paradas por motivo (barras simples) e quem
   operou, com horas e custo de cada pessoa.
4. **Custo por hora** cadastrável **por recurso e por pessoa** (decisão do
   Iago). Quem edita: `diretoria` e `admin`. Quem vê valores em R$: os mesmos.
5. Períodos: Hoje, Semana, Mês.
6. Mockup aprovado: `.superpowers/brainstorm/4931-1792150485/content/aba-diretoria.html`
   (Painel A em cima, Ficha B embaixo, na mesma aba). Os números do mockup são
   inventados.

## Não metas

- Salário real/folha de pagamento, encargos, rateio: o campo é só "valor da
  hora" digitado pela diretoria.
- Exportar para Excel/PDF, agendar relatório, previsão, comparativo com meta.
- Mudar qualquer regra de OEE, turno, parada ou apontamento.
- Abrir a aba para outros níveis (PCP, gerência, supervisão...) nesta entrega.
- Alterar telas existentes (Visão Geral, Relatórios, Andon).

## Anti-metas (falha mesmo que "funcione")

- Tela cheia de gráficos e "porquês": o texto pronto vem primeiro, o detalhe
  é secundário.
- Número da aba diferente do mesmo número em Visão Geral/OEE/Relatórios.
  A aba **não recalcula** regra de negócio; consome os serviços existentes
  (fonte única).
- Valor em R$ visível ou entregue pela API a quem não é `diretoria`/`admin`
  (inclusive em respostas de outras rotas, logs ou relatórios existentes).
- Custo calculado em cima de parada planejada.

## Decisões do Iago

- Custo por hora **por recurso e por pessoa**.
- Editam o custo: `diretoria` e `admin`.
- Só **parada não planejada** entra no custo (mesma classificação do OEE:
  parada planejada não afeta OEE; não planejada afeta).
- Períodos Hoje / Semana / Mês.
- A aba só junta e resume dados que o sistema já calcula.
- Começar pela diretoria; ir refinando com o uso ("depois vamos aprimorando").

## Decisões minhas (marcadas como chute — Iago, corrija se errar)

- **Fórmula do custo da parada:** horas paradas x (custo/h do recurso + soma
  do custo/h das pessoas que estavam alocadas ao recurso durante a parada).
  O sistema já mantém a equipe durante a parada (ver
  `operator_participation.py` e o teste "parada mantém a equipe"). Pessoa ou
  recurso sem custo cadastrado conta como R$ 0 e a tela avisa
  "sem custo cadastrado" em vez de esconder.
- **Onde cadastrar o custo:** seção "Custos" **dentro da própria aba
  Diretoria** (lista de recursos e de pessoas com um campo "R$/h"
  editável), em vez de espalhar nas telas de Recursos e Usuários. Mais fácil
  para eles.
- **Custo do trabalho (não só da parada):** a ficha também mostra o custo das
  horas trabalhadas, mesma fórmula. É a mesma conta, e responde "quanto custou
  o recurso X".
- **Histórico do valor:** o valor/hora vale a partir de quando é salvo; não
  reescreve o custo de períodos passados nesta primeira versão. (Se a
  diretoria alterar o valor, o passado recalculado pode mudar. Ver Aberto.)

## Decisões fechadas após a revisão do desenho (minhas — Iago, corrija se errar)

- **"Pessoa" = operador do chão de fábrica** (cadastro de operadores, crachá,
  tabela de participações), **não** conta de login. O custo por hora da
  pessoa fica ligado ao operador.
- **Ranking do Painel:** "onde mais se perde" ordena por **horas paradas não
  planejadas** (funciona mesmo antes de qualquer custo ser cadastrado); R$ e
  motivo principal são colunas. "Melhor/pior setor" usa o **OEE** já
  existente (mesma definição da Visão Geral).
- **Custo faltando:** o total de R$ mostra o que está cadastrado e um aviso
  visível "faltam custos de N recursos/pessoas — o valor real é maior". Nunca
  mostrar R$ baixo sem esse aviso. A API devolve um indicador "completo /
  parcial" por número em R$.
- **"Trabalhou" e "parado":** reutilizar exatamente as definições de
  disponibilidade/estado do recurso do OEE, sem recalcular. **Não** prometer
  que trabalhado + parado = turno. O tempo sem demanda e o fora de turno
  aparecem como linhas separadas ("sem demanda: X h", "fora do turno: X h") e
  **não geram custo de parada** (só parada não planejada gera).
- **Períodos:** "Hoje" = o dia de calendário (igual ao filtro Hoje da Visão Geral). "Semana" = semana corrente até agora; "Mês" = mês
  corrente até agora. O construtor confere o que a Visão Geral já aceita e
  alinha com ela; a base de horas disponíveis é somada do calendário/turnos
  na mesma janela.

## Restrições do projeto (leia antes de planejar)

- **Os valores de R$ ficam em tabela separada** (recurso/operador -> valor
  por hora), nunca como coluna nas tabelas de recursos ou operadores, que
  rotas existentes podem devolver inteiras. Só as rotas novas, restritas a
  `diretoria`/`admin`, leem essa tabela.

- Risco **R3**: campo novo no banco (migration), dado financeiro sensível,
  números que a diretoria usa para decidir. Exige guardião do domínio MES/OEE,
  QA e revisão independente.
- Migration segue o processo do projeto; testar primeiro no banco de teste. **Não
  aplicar no banco REAL sem o ok do Iago.**
- Mudança visual exige imagem da tela como prova + autocrítica "Eu fiz certo?
  Por quê?" antes de commitar (regra do projeto).
- Simplicidade: nada de fricção extra; sem botão flutuante; linguagem do
  chão de fábrica/diretoria, sem jargão.
- Sistema de áreas/permissões: `app/core/areas.py` e `app/core/permissions.py`
  são a fonte única de quem vê o quê; `mes/services/` têm os cálculos de
  OEE, paradas e equipe; `web/src/pages/` o frontend (React/TypeScript);
  `backend/api/routers/` as rotas.
- Documentação de OEE/regras corporativas e de estados do recurso existente
  prevalece sobre qualquer definição nova.

## Deixado para quem constrói

- Estrutura exata das tabelas/colunas e número da migration.
- Formato da rota (um endpoint resumido por tela ou um só).
- Como obter, por recurso, "horas disponíveis do turno" (o "31 h de 40 h")
  usando o calendário/turnos que já existem.
- Visual final (seguir o design system atual); o mockup é só guia de conteúdo.
- Testes: unidade para a fórmula do custo e para as permissões; um teste
  confirmando que `gestor`, `lider` e demais níveis não recebem R$.

## Aberto (não bloqueia o plano)

- Se a diretoria mudar o valor/hora, o passado muda? Versão 1: sim (usa o valor
  atual). Se virar problema, guardar valor com data de vigência.
- Pessoas que operam mais de um recurso ao mesmo tempo: usar a regra de
  participação que o sistema já tem; não inventar rateio novo.
