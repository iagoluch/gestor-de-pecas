# Validação visual completa — 2026-09-14

Varredura sistemática de todas as telas do sistema em busca de texto cortado,
fonte inconsistente, itens desalinhados, cards mal dimensionados, sobreposição
e quebra de responsividade.

## Como foi feito

- Pré-visualizações isoladas (`.claude/launch.json`): `gestor-preview-visual`
  (porta 8010, todos os perfis via login) e `gestor-preview-andon` (porta 8011,
  alterna TV/gerencial pelo cookie `preview_perfil`). Nenhum banco operacional
  foi tocado.
- `npm run build` antes de abrir a preview e depois de **cada** correção de CSS
  (a preview serve `web/dist`, não lê o fonte ao vivo).
- Além da inspeção por captura de tela, foi usado um auditor de layout injetado
  na página (`getBoundingClientRect` + estilo computado) que, em cada rota,
  detecta automaticamente:
  - rolagem horizontal da página;
  - texto cortado no eixo X e no eixo Y (`scrollWidth/scrollHeight` maior que
    a caixa, sob `overflow: hidden`/`clip`);
  - elemento saindo da viewport (ignorando containers roláveis);
  - alturas desiguais entre cards da **mesma linha** de um grid;
  - sobreposição real entre irmãos em fluxo normal;
  - fonte abaixo de 10px.
- Cada tela foi medida em pelo menos duas larguras: **1440px** e **1024px**.
  Andon e Solda também em **1920×1080** (TV real), e o login do Dev Observatory
  em **420px**.

## Cobertura

| Área | Telas / estados |
| --- | --- |
| Login | Login principal; login do Dev Observatory; página de recusa do Dev Observatory |
| Operador | Seletor de recurso (Corte, Dobra), Workbench Dobra (vazio, com OP, estado de erro), popup Setup e Qualidade, Workbench Corte (tarefa/planos/chapas), Destaque, Solda (perfil sem estação) |
| Andon | Modo TV (perfil `andon`) a 1920×1080; modo gerencial a 1440 |
| Solda | `/welding-management` TV a 1920×1080; gerencial a 1440 e 1024; sub-abas Visão geral, Atrasos, Entregas; estações expandidas |
| Tela inicial | Visão Geral, Setores, Alertas, Andon (redirect), Solda (redirect), Metas, IA, Pausas, Crachás; gaveta "Entender" (insight drawer) |
| Consulta Operacional | Visão Geral, Recursos, OPs em andamento, Tempo MES |
| Produção | Ordens, Realizada, Planejado × Realizado |
| Análises | OEE, Horas & Utilização, Paradas, Setup, Qualidade, Tempo padrão, Cronoanálise, Capacidade, Confiabilidade |
| Auditoria | Apontamentos, Inconsistências, Confiabilidade dos dados |
| Relatórios | Gerencial, Produção, Perdas, Indicadores, Dados analíticos |
| Rastreabilidade | OP/Produto, Linha do tempo, Lote/Material/Nesting |
| Dev Observatory | Tela de login (renderizada), página de recusa, layout autenticado (HTML/CSS estático servido isoladamente) |

**Total: 55 telas/estados, cada uma em 2 ou mais larguras.**

---

## Defeitos encontrados e CORRIGIDOS

### 1. Fonte inconsistente no mesmo grid de KPIs — Análises › OEE

**Antes:** na linha AE / Produtividade / Utilização, o texto "Dados
insuficientes" era renderizado a **23px, cor de texto normal e com reticências
por `white-space: nowrap`**, enquanto o cartão OEE logo acima renderizava
exatamente o mesmo texto a **17px, cinza e quebrando linha**. Dois cartões
idênticos, mesma frase, tipografias diferentes.

**Causa raiz (não era CSS):** a regra
`.metric-card[data-availability="dados_insuficientes"] .metric-card__value`
depende do atributo `data-availability`. Quando o próprio objeto do indicador
vem ausente do backend, o helper `metric()` já devolve a frase "Dados
insuficientes", mas a prop `availability` ia `undefined` e o `MetricCard` caía
no default `"disponivel"` — isto é, o cartão era estilizado como se tivesse um
número. O padrão correto já existia isolado em uma linha do arquivo
(`?? "dados_insuficientes"`), sem ser aplicado nas demais.

**Correção:** fonte única de verdade ao lado de `metric()`, em
`web/src/pages/analytics/AnalyticsPages.tsx`:

```ts
function metricState(metric: MetricValue | undefined): Availability {
  return metric?.availability ?? "dados_insuficientes";
}
```

Aplicada nos 8 cartões que liam `x?.availability` de um objeto opcional, e o
`?? "dados_insuficientes"` acrescentado nos 3 cartões que liam
`data?.availability` (Utilização do período, MTBF, MTTR) — nestes últimos a
própria expressão do *valor* já usava esse fallback, só a prop de estilo não.

**Depois:** os sete cartões da tela de OEE usam a mesma tipografia de estado.
Afeta também Capacidade/Gargalos e Confiabilidade, que tinham o mesmo padrão.

### 2. Explicação do cartão de KPI cortada — Tela inicial › Visão Geral, Análises › Confiabilidade

**Antes:** `.metric-card__detail` tinha `-webkit-line-clamp: 2`. A 1440px, onde
o grid abre 5 colunas e os cartões ficam estreitos, frases como *"Nenhum
registro de quantidade foi encontrado para o período e os filtros informados."*
e *"Não há quantidade boa, refugo ou retrabalho no filtro para calcular o
FTT."* eram cortadas com reticências. Em Confiabilidade a frase precisava de 5
linhas e mostrava 2.

**Correção:** `-webkit-line-clamp: none` na regra base
(`web/src/styles/global.css`). O cartão tem `min-height`, não altura fixa, e o
grid estica todos os cartões da linha juntos — a linha só fica alguns pixels
mais alta, e permanece uniforme. As sobreposições do Andon
(`.andon-summary-grid .metric-card__detail { -webkit-line-clamp: 1 }`), onde a
altura **é** fixa por causa da TV, continuam valendo e não foram tocadas.

**Depois:** as três frases aparecem inteiras; os quatro/cinco cartões da linha
continuam com a mesma altura.

### 3. Rótulo espremido pela barra decorativa — Análises › Paradas (Pareto por motivo)

**Antes:** `.bar-list__row` usava `minmax(95px, 1fr) minmax(120px, 3fr) 76px`.
Com 3fr, a barra ficava com ~168px e o rótulo era empurrado para o seu mínimo
de 95px — "Aguardando ponte rolante" (139px) virava "Aguardando ponte rol…",
"Aguardando material" e "Troca de ferramenta" idem.

**Correção:** inverter a prioridade da sobra, mantendo os mínimos —
`minmax(95px, 1.4fr) minmax(120px, 1fr) 76px`. O rótulo é o dado; a barra é só
a leitura visual dele. Quando a linha aperta, ambos voltam aos mínimos e o
`text-overflow` volta a agir como degradação, não como comportamento normal.

**Depois:** os três motivos aparecem por extenso e a barra continua legível.

### 4. Mesmo defeito na Solda — aba Atrasos (Atraso por estação)

**Antes:** `.welding-ranking li` usava `minmax(70px, 1fr) minmax(60px, 2fr)
auto` — "Estação ainda não definida" (148px) cortada em 88px.

**Correção:** mesma proporção do item 3, em `web/src/styles/welding.css`:
`minmax(70px, 1.4fr) minmax(60px, 1fr) auto`.

### 5. Rótulos do gráfico de barras da Solda indistinguíveis

**Antes:** `.welding-barchart__label` tinha `white-space: nowrap` +
`text-overflow: ellipsis` e teto de largura fixo (78px base / 100px TV / 140px
TV grande). Como **todos** os MACROs começam por "CONJ. SOLD.", os sete rótulos
apareciam como "CONJ. SOLD. CA…", "CONJ. SOLD. FR…", "CONJ. SOLD. MU…" — o
eixo do gráfico ficava sem informação nenhuma, inclusive na TV a 1920×1080.

**Correção:** rótulo em até 3 linhas, ocupando a largura do próprio grupo:

```css
.welding-barchart__label {
  flex: 0 0 auto;
  max-width: 100%;
  height: 3.6em;            /* reserva fixa: ver nota abaixo */
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
  ...
}
```

Os tetos `max-width: 100px` / `140px` das regras de TV foram removidos (o
`font-size` continua).

**Por que altura fixa e não `auto`:** `.welding-barchart__bar` tem `height:
100%` dentro do grupo. Se cada grupo reservasse uma altura diferente de rótulo,
a barra de cada grupo teria uma altura disponível diferente e **o mesmo valor
desenharia alturas diferentes** — trocaria um defeito por outro pior.

**Depois:** os sete MACROs legíveis por extenso na TV e no gerencial; barras com
a mesma altura de referência; a TV continua cabendo sem rolagem
(`scrollHeight == innerHeight == 1080`).

### 6. Quebra de layout da Solda a 1024px

**Antes:** `.welding-macros__body` só desfazia as duas colunas abaixo de 900px.
A 1024px a tabela pivô (6 colunas, faixa `auto`) consumia a largura e sobrava o
mínimo de 280px para o gráfico: sete grupos de ~28px, rótulos ilegíveis em
qualquer formatação.

**Correção:** ponto de quebra movido de `max-width: 900px` para
`max-width: 1180px`, que é o mesmo que o resto do sistema já usa em
`global.css` para desfazer grids de duas colunas — nenhum breakpoint novo foi
inventado. A regra de TV (`.welding-page--tv .welding-macros__body`) tem
especificidade maior e não é afetada.

**Depois:** a 1024px a tabela, a pizza e o gráfico empilham; o gráfico recebe a
largura inteira e os rótulos ficam legíveis. Zero achados do auditor nessa
largura.

### 7. Nome do operador com reticências — barra lateral do Operador a 1024px

**Antes:** `.operator-profile span` tinha `overflow: hidden; text-overflow:
ellipsis; white-space: nowrap` — "Operador Dobra Visual" (123px) cortado em
110px. O bloco equivalente da barra gerencial (`.profile-card span`) **não**
tem nenhuma dessas regras e quebra linha normalmente: era uma inconsistência
entre dois componentes irmãos.

**Correção:** `.operator-profile span { min-width: 0; overflow-wrap: anywhere;
font-size: 12px; }`. O cartão tem `min-height: 120px` e sobra vertical de
folga.

### 8. Login do Dev Observatory sem meta viewport

**Antes:** `_LOGIN_PAGE` em `backend/api/routers/dev_observatory.py` não tinha
`<meta name="viewport">` — o `index.html` da própria ferramenta tem. Resultado:
num viewport de 420px o navegador assumia a largura padrão de **980px** e
reduzia a página inteira, deixando o formulário minúsculo. Também usava
`height: 100vh` sem `padding`, então numa janela baixa o cartão ficaria
cortado, sem rolagem possível.

**Correção:** meta viewport acrescentado; `height: 100vh` → `min-height: 100vh`
com `padding: 16px` e `box-sizing: border-box`. O mesmo par de problemas
existia na `_DENIED_PAGE`, corrigido junto (mais `width: 100%` +
`box-sizing` no `main`, que só tinha `max-width`).

**Depois:** `innerWidth` volta a 420 e o formulário fica em tamanho real; 0
achados do auditor.

---

## Encontrado e apenas DOCUMENTADO (exige decisão de design ou é fora de escopo)

### A. Densidade da TV do Andon: fontes de 6px a 9px e textos cortados

No modo `--single-view` (que vale tanto para o perfil TV quanto para o
gerencial) o Andon comprime tudo para caber **sem rolagem**, com um sistema
muito afinado de `--andon-card-width` por densidade e por breakpoint, e
comentários explícitos no CSS de que "nenhum recurso deve aparecer maior que o
outro". Consequências medidas:

- 18 textos abaixo de 10px, chegando a **6px** em
  `.andon-page--single-view .andon-card__operation small` e **7px** em
  `.andon-resource-group__header span`;
- 8 textos cortados a 1920×1080: "Aguardando ponte rolante" (182px em 136px),
  "Chapa cortada 310" (89px em 75px), "Torno Mecânico" (99px em 94px), entre
  outros;
- a 1440 no modo gerencial o corte é maior ainda: "Laser Ensis 3015" →
  "Laser Ensis …", "Plasma TerraBla…", "Fresadora FT…".

**Não corrigido de propósito:** qualquer correção real aqui significa cartão
maior ou fonte maior, o que desfaz a decisão "tudo cabe sem rolagem". É uma
escolha de produto (quanto cabe × quanto se lê numa TV de chão de fábrica), não
um defeito de CSS.

### B. `.andon-header` é CSS morto

`global.css` (linhas ~408-418) define `.andon-header`, `.andon-header__brand`,
`.andon-header__title`, `.andon-header__status` e `.andon-fullscreen`, mas o
`AndonPage.tsx` não renderiza mais cabeçalho nenhum — a única classe montada é
`andon-page andon-page--single-view ${tv|manager}`. São ~11 regras sem
consumidor. Limpeza, não defeito visual: não removi porque sem git a remoção é
a mudança mais difícil de desfazer, e não afeta nada renderizado.

### C. "Management View" em inglês no meio de uma UI em português

Título de `/inicio/visao-geral`, `/inicio/setores` e `/inicio/alertas`. É
consistente nas três telas e está afirmado em dois testes
(`management.test.tsx`, `operator.test.tsx`), ou seja, é nome adotado e não
descuido. Se a intenção for padronizar tudo em português, é uma decisão de
produto — troca de nome, não correção visual.

### D. Alturas diferentes entre as duas colunas de um painel

- `.welding-panel` (Solda › Atrasos): cartão estreito de 105px ao lado de
  tabela de 318px, com `align-items: start`.
- `.operator-workbench__top`: bloco de ações de 294px ao lado do cartão de
  desenho de 85px.

Nos dois casos são cartões de naturezas diferentes, alinhados ao topo — o
oposto do bug corrigido hoje no `welding-macros__body`, onde a coluna
*precisava* esticar porque continha um gráfico proporcional. Aqui esticar só
criaria área vazia. Deixado como está.

### E. Pizza da Solda alinhada à esquerda num cartão largo

`.welding-pie` é `display: flex; align-items: center` sem `justify-content`:
quando o painel empilha (agora ≤1180px) sobra bastante espaço à direita da
legenda. Centralizar é defensável, mas gráfico+legenda alinhados à esquerda
também é um padrão normal — não é um defeito objetivo, então não mexi.

### F. Escala de micro-rótulos com três valores

`.metric-card__topline` usa 11px, `.resource-card dt` usa 10px e
`.cutting-card dl dt` / `.cutting-plan header small` usam 9px, todos no mesmo
papel (rótulo em caixa alta acima de um valor). Cada tela é internamente
consistente; entre telas, não. Unificar é uma decisão de design system.

### G. Achados de dado (não de CSS) na pré-visualização

- `/analises/oee`: `extended_metrics` (AE, Produtividade, Utilização) vem vazio
  e "Perdas por motivo" mostra "Não disponível" em todos os seis motivos. É o
  que expôs o defeito nº 1, mas a ausência em si é do fixture/backend.
- Operador Solda: "Perfil de Solda sem estação fixa" — o fixture da preview não
  vincula estação ao login `visual-solda`. Estado tratado corretamente pela UI.
- `OP-VISUAL-105` não existe no catálogo da preview (existe só como evento de
  estado), então "Carregar roteiro" cai no cartão de erro. Serviu para validar
  o layout do estado de erro, que está correto.

Nenhum desses foi alterado — são dados, não interface.

---

## Validação executada

| Verificação | Resultado |
| --- | --- |
| `npx tsc -b` | limpo |
| `npx vitest run` (suíte completa — justificada porque `global.css` foi alterado) | **12 arquivos, 156 testes, todos passando** |
| `python -m unittest tests.test_dev_observatory` | **19 testes, todos passando** |
| `npm run build` | limpo (6 builds durante o trabalho) |
| Auditor de layout, 34 rotas gerenciais @1440 | 0 achados |
| Auditor de layout, 34 rotas gerenciais @1024 | 0 achados |
| Solda gerencial @1440 e @1024, 3 sub-abas | 0 achados |
| Solda TV @1920×1080 | 0 achados; cabe sem rolagem |
| Andon TV @1920×1080 | cabe sem rolagem; restam só os itens do achado A |
| Operador (4 setores) @1440 e @1024 | 0 achados fora de `tiny-font` |
| Dev Observatory login @1440 e @420 | 0 achados |

## Arquivos alterados

- `web/src/pages/analytics/AnalyticsPages.tsx` — helper `metricState()` + 11 call sites
- `web/src/styles/global.css` — `.metric-card__detail`, `.bar-list__row`, `.operator-profile span`
- `web/src/styles/welding.css` — `.welding-barchart__label`, breakpoint de `.welding-macros__body`, `.welding-ranking li`, tetos de largura nas regras de TV
- `backend/api/routers/dev_observatory.py` — meta viewport e `min-height` em `_LOGIN_PAGE` e `_DENIED_PAGE`
