# DESIGN.md — Gestor de Peças

Extraído do `AGENTS.md` em 2026-09-29; tem a mesma força normativa do `AGENTS.md`.

## Contrato definitivo de design e fidelidade visual

Esta seção é normativa. Para qualquer tarefa que toque interface, layout, ícones, fontes, cores, gráficos, tabelas, responsividade ou composição visual, estas regras têm o mesmo peso das regras de negócio do sistema.

O objetivo não é criar uma interface "parecida". O objetivo é preservar e reproduzir o design aprovado do Gestor de Peças com fidelidade mensurável.

### Hierarquia de fonte de verdade visual

Quando houver dúvida ou conflito, usar esta ordem de precedência:

1. pedido visual explícito do usuário na tarefa atual;
2. `assets/screens/screens - atuais/*.png` — referência visual oficial vigente;
3. `web/src/styles/tokens.css` — tokens e métricas oficiais vigentes;
4. `web/src/styles/global.css` — composição, responsividade e estados visuais;
5. `web/src/components/` e `web/src/pages/` — comportamento dos componentes compartilhados;
6. `web/src/test/` — contratos automatizados de interface e comportamento;
7. `assets/screens/screens - legacy/*.png` — somente referência histórica, nunca autoridade quando divergir das telas atuais.

Não usar `legacy` para desfazer uma decisão presente nas telas atuais.

Se um pedido explícito aprovar uma mudança visual nova, atualizar de forma coerente os tokens, componentes, testes e referências visuais afetadas. Não deixar o sistema com duas definições contraditórias do mesmo padrão.

### Catálogo visual oficial

O catálogo atual contém 24 telas oficiais em:

```text
assets/screens/screens - atuais/
```

As 24 imagens têm viewport capturado de `1920 x 1061`.

A implementação Web usa como base lógica:

```text
MOCKUP_BASE_WIDTH  = 1920
MOCKUP_BASE_HEIGHT = 1080
```

Essa diferença é intencional: os PNGs representam a área útil capturada da aplicação, enquanto o layout responsivo é calculado sobre a referência lógica de 1920 x 1080.

Portanto:

- não alterar `MOCKUP_BASE_WIDTH` ou `MOCKUP_BASE_HEIGHT` para 1920 x 1061 apenas para coincidir com o PNG;
- ao medir screenshots, considerar o fator de escala do layout;
- no PNG atual de 1920 x 1061, por exemplo, a sidebar aparece com cerca de 321 px e o header com cerca de 107 px porque `1061 / 1080 ~= 0,9824`;
- na referência lógica de 1920 x 1080, as dimensões estruturais oficiais continuam sendo 327 px para a sidebar e 109 px para o header.

### Princípio visual

A identidade do Gestor de Peças é uma interface industrial limpa, funcional e de alta legibilidade, com:

- navegação lateral azul-marinho escura;
- header branco;
- área de conteúdo cinza muito clara;
- cards brancos com borda fria discreta;
- azul vivo como cor primária de ação e seleção;
- cores semânticas para sucesso, alerta e erro;
- tipografia Arial;
- ícones oficiais simples e nítidos;
- cantos levemente arredondados;
- ausência de efeitos decorativos desnecessários.

Não converter o projeto para outra linguagem visual, como Material, Fluent, glassmorphism, neumorphism, neon, gradientes decorativos, sombras fortes ou componentes excessivamente arredondados, salvo pedido explícito do usuário.

### Paleta oficial

As cores devem vir de `UI_COLORS` em `app/core/styles.py`. Não criar uma segunda paleta paralela.

| Token | Cor | Uso principal |
|---|---:|---|
| `bg` | `#F5F7FA` | fundo geral do conteúdo |
| `surface` | `#FFFFFF` | cards, header, campos e superfícies |
| `surface_alt` | `#F1F3F6` | zebra de tabelas e superfícies secundárias |
| `border` | `#C7D3E2` | bordas de cards, tabelas e controles |
| `divider` | `#DDE5EF` | divisórias leves |
| `text` | `#081630` | texto principal |
| `muted` | `#71809D` | texto secundário |
| `primary` | `#0866F5` | ação principal, seleção e foco |
| `primary_hover` | `#075BD8` | hover do primário |
| `primary_soft` | `#E8F2FF` | seleção e estado azul suave |
| `primary_dark` | `#052B55` | azul profundo auxiliar |
| `accent` | `#16A34A` | sucesso |
| `accent_soft` | `#EAF8EF` | sucesso suave |
| `warning` | `#F59E0B` | atenção |
| `warning_soft` | `#FFF6E6` | atenção suave |
| `danger` | `#EF3340` | erro/crítico |
| `danger_soft` | `#FFF0F1` | erro/crítico suave |
| `sidebar` | `#001E3F` | fundo principal da sidebar |
| `sidebar_active` | `#0866F5` | aba ativa |
| `sidebar_button` | `#082C55` | aba inativa |
| `sidebar_button_hover` | `#0C3765` | hover da aba |
| `sidebar_panel` | `#03264B` | cards internos da sidebar |
| `sidebar_border` | `#0A426F` | borda dos cards da sidebar |
| `sidebar_text` | `#FFFFFF` | texto da sidebar |
| `ok` | `#42D85A` | indicador positivo |
| `info` | `#0866F5` | informação |
| `alert` | `#F5B400` | alerta |
| `critical` | `#EF3340` | crítico |
| `orange` | `#FF7100` | categoria auxiliar |
| `purple` | `#7047E8` | categoria auxiliar/relatórios |
| `teal` | `#20A7A1` | categoria auxiliar |

Regras de cor:

- usar o token semântico, não copiar HEX arbitrariamente para novos componentes;
- não alterar a cor de um SVG oficial em disco;
- tint em memória só é permitido quando o componente existente já prevê tint semântico, como em `tinted_official_icon`;
- manter contraste equivalente ao design aprovado;
- não usar preto puro como texto padrão: o texto oficial é `#081630`;
- não trocar o fundo do conteúdo para branco: a separação `bg` versus `surface` faz parte do design.

### Tipografia oficial

Fonte padrão:

```text
Arial
```

A fonte deve vir de `DEFAULT_UI_FONT` / `UI_FONT`. Não misturar famílias tipográficas na interface principal.

Escala tipográfica oficial usada pelo stylesheet:

| Papel | Tamanho | Peso |
|---|---:|---:|
| título da página | 31 px | 700 |
| subtítulo da página | 12 px | normal |
| título de seção | 17 px | 700 |
| KPI normal — título | 13 px | normal |
| KPI normal — valor | 21 px | 700 |
| KPI normal — detalhe | 11 px | normal |
| KPI grande — título | 16 px | 700 |
| KPI grande — valor | 48 px | 700 |
| KPI grande — detalhe | 14 px | normal |
| KPI compacto — título | 14 px | 700 |
| KPI compacto — valor | 34 px | 700 |
| KPI compacto — detalhe | 12 px | normal |
| título de card de seleção | 32 px | 700 |
| texto de status | 14 px | normal |
| navegação | 16 px | normal; 700 quando ativa |
| tabela | 13 px | normal |
| cabeçalho de tabela | 13 px | 700 |

Tamanhos específicos definidos diretamente por componentes existentes devem ser preservados. Exemplos:

- formulário de apontamento: título e máquina em Arial 25 bold;
- label `Código da OP`: Arial 13 bold;
- input principal de OP: Arial 15;
- mensagem de sucesso: Arial 14 bold;
- saudação da sidebar: escala a partir de 16;
- operador da sidebar: escala a partir de 12.

Não "modernizar" a fonte, reduzir títulos ou alterar pesos só por preferência estética.

### Espaçamento e ritmo

Tokens oficiais de espaçamento em `SPACING`:

```text
xs   = 4
sm   = 8
md   = 12
lg   = 16
xl   = 24
page = 27
```

Regras:

- margem padrão da área de conteúdo: 27 px na escala 1.0;
- espaçamento estrutural padrão entre blocos da página: 16 px;
- espaçamento interno de card compartilhado: normalmente 14 x 12 px;
- toolbar compartilhada: 16 x 12 px com gap de 12 px;
- títulos de seção: ícone e texto com gap de 10 px;
- preferir os tokens e helpers existentes a valores novos;
- quando um valor específico já estiver comprovado no mockup ou teste, preservar esse valor;
- não aumentar padding para "dar mais respiro" sem comparar com o mockup.

### Raios, bordas e elevação

Tokens de raio:

```text
control = 5
card    = 10
panel   = 12
pill    = 9
```

Implementação atual relevante:

- cards: borda de 1 px `#C7D3E2`, raio 10 px;
- toolbar: borda de 1 px, raio 9 px;
- card de seleção: borda de 1 px, raio 12 px;
- botão comum: raio 6 px;
- campos: raio 5 px;
- badge de status: raio 8 px no delegate;
- tabelas: sem arredondamento visual no corpo (`border-radius: 0`).

Não adicionar sombra a todos os cards. O design atual depende majoritariamente de fundo + borda + espaçamento, não de elevação pesada.

### Estrutura principal da janela

A janela deve preservar a estrutura:

```text
+----------------------+-----------------------------------------+
|                      | Header branco                            |
| Sidebar escura       +-----------------------------------------+
| fixa à esquerda      |                                         |
|                      | Conteúdo #F5F7FA                        |
|                      | com margem responsiva                    |
|                      |                                         |
+----------------------+-----------------------------------------+
```

Dimensões de referência em escala 1.0:

```text
janela lógica:        1920 x 1080
sidebar:              327 px
header:               109 px
margem da página:      27 px
separação de página:   16 px
mínimo da janela:     1024 x 680
```

Não mover a navegação para o topo, não transformar a sidebar em drawer e não eliminar o header sem pedido explícito.

### Responsividade oficial

O fator de escala estrutural é:

```python
scale = max(0.64, min(1.0, width / 1920, height / 1080))
```

Regras derivadas:

- sidebar: `max(220, round(327 * scale))`;
- header: `max(76, round(109 * scale))`;
- margem de conteúdo: `max(14, round(27 * scale))`;
- usar `_s(valor)` para dimensões estruturais que devem acompanhar a escala;
- usar `_sf(valor)` para fontes escaláveis quando o componente já seguir essa estratégia;
- em sidebar extensa, usar o modo denso já implementado em vez de esconder itens;
- não permitir sobreposição de avatar, navegação, relógio, status e crédito;
- preservar funcionalidade em 1920x1080, 1600x900 e 1366x768;
- 1024x680 é o limite mínimo suportado da janela principal;
- scroll deve ser introduzido somente onde a arquitetura visual da tela realmente exige; não envolver indiscriminadamente toda página em containers roláveis.

Não substituir o sistema responsivo existente por scaling de screenshot, zoom global ou coordenadas absolutas.

### Sidebar

A sidebar é um elemento permanente de identidade e navegação.

Regras de referência em escala 1.0:

- largura: 327 px;
- fundo: `#001E3F`;
- margens do layout: aproximadamente 15 / 19 / 16 / 18 px;
- gap normal entre blocos: 9 px;
- logo oficial recortado: 254 x 52 px;
- avatar: 60 x 60 px;
- card de perfil oficial: 296 x 120 px em 1920x1080;
- botão de navegação: altura de referência 61 px;
- ícone de navegação: caixa de referência 62 x 47 px;
- botão inativo: `#082C55`;
- botão ativo: `#0866F5`, texto bold e faixa esquerda azul-clara;
- hover: `#0C3765`;
- texto da sidebar: branco;
- cards internos: `#03264B` com borda `#0A426F`;
- relógio, status de conexão e crédito do desenvolvedor permanecem visualmente agrupados no rodapé.

Na resolução lógica 1920x1080, os testes Web e a comparação com as capturas oficiais validam também posições-chave da sidebar. Alterações nessas posições só são aceitáveis quando o design for explicitamente revisado.

Não:

- trocar os ícones da navegação por emojis;
- reduzir a sidebar a ícones sem texto;
- mudar o estado ativo para outra cor;
- remover o bloco de identidade/operador por conveniência de layout;
- alterar a proporção do logo.

### Header

O header deve permanecer:

- branco;
- separado do conteúdo por divisor inferior `#DDE5EF` de 1 px;
- altura de referência 109 px;
- com margem interna aproximada de 28 px horizontal e 12 px vertical;
- título principal alinhado à esquerda;
- ações `Ajuda` e `Configurações` alinhadas à direita quando permitidas;
- ícones oficiais de 30 x 30 px nas ações;
- botão de voltar de 48 x 48 px quando aplicável;
- cartão de sincronização de catálogo somente quando a tela pedir esse estado.

A visibilidade de Configurações continua dependente de permissão; não alterar regra de autorização em nome de fidelidade visual.

### Área de conteúdo e cards

O conteúdo usa `#F5F7FA` como base e `#FFFFFF` como superfície.

Cards compartilhados devem reutilizar os componentes em `web/src/components/` ou composição equivalente já existente antes de criar uma implementação nova.

Padrão de card:

- fundo branco;
- borda de 1 px `#C7D3E2`;
- raio 10 px;
- tipografia escura;
- hierarquia clara entre título, valor e detalhe;
- alinhamento coerente dentro da família do componente.

Não criar cards com:

- gradientes;
- sombra intensa;
- contorno neon;
- ícones 3D;
- fundos coloridos arbitrários;
- raio muito maior que o padrão.

### KPIs

Os KPIs devem usar `KpiCard` e seus papéis tipográficos existentes.

Na Tela Inicial, a organização oficial dos KPIs em escala ampla é:

```text
Linha 1: OPs Ativas | Tarefas Abertas | Hoje | Banco de Dados
Linha 2: Dobra | Usinagem | Corte | Serra | Almoxarifado
```

Os ícones de KPI dessa tela usam recorte circular oficial de 48 x 48 px na referência 1920x1080.

Na Visão Geral da Consulta Operacional, o padrão atual é de 10 KPIs compactos organizados em duas linhas de 5 cards.

Ao adicionar KPI novo:

- reutilizar o mesmo componente;
- escolher ícone existente ou criar asset novo no mesmo padrão somente com aprovação;
- manter hierarquia título / valor / detalhe;
- manter altura uniforme dentro da mesma linha;
- não quebrar a grade para destacar um KPI sem referência visual aprovada.

### Cards de seleção

`SelectionCard` é o padrão para telas de escolha de máquina, Consulta Operacional e Relatórios.

Comportamento visual:

- superfície branca;
- borda fria de 1 px;
- raio 12 px;
- hover com borda primária de 2 px e fundo `#FBFDFF`;
- ícone/imagem centralizado;
- título em destaque;
- cursor de clique;
- proporção do asset preservada.

Para seleção de máquinas de Dobra, Usinagem e Serra, a grade oficial segue:

```text
[ máquina 1 ] [ máquina 2 ]
      [ máquina 3 ]
```

Ou seja: duas opções na primeira linha e a terceira centralizada abaixo.

Dimensões de referência usadas pela implementação:

- largura por card: aproximadamente 510–520 px escalados;
- altura por card: aproximadamente 405–415 px escalados;
- gap horizontal e vertical: 36 px escalados;
- container de seleção: até 1120 px de largura.

A tela de seleção de Relatórios usa dois cards grandes lado a lado. Não substituir por lista, combo ou tabs sem pedido explícito.

### Formulários de apontamento

As telas de registro de Dobra, Usinagem e setores que reutilizam esse padrão devem manter o formulário centralizado.

Padrão atual:

- card principal centralizado;
- largura de referência escalada em torno de 930 px, limitada a 1035 px;
- ícone do setor/máquina no topo;
- título do formulário centralizado;
- nome da máquina centralizado;
- label `Código da OP` acima do campo;
- input principal com altura mínima de 50 px;
- mensagem operacional/sucesso centralizada abaixo;
- fila da máquina em card separado, alinhado ao mesmo eixo e à mesma largura máxima.

Não transformar esse formulário em layout de duas colunas sem aprovação visual.

### Botões

Botão comum:

- altura mínima 38 px;
- padding 5 x 16 px;
- fundo branco;
- borda `#C7D3E2`;
- raio 6 px;
- texto bold;
- hover com borda/texto `#0866F5`.

Variantes:

- `primary`: fundo `#0866F5`, texto branco;
- `danger`: fundo `#EF3340`, texto branco;
- `success`: fundo `#16A34A`, texto branco.

Estados disabled devem continuar cinza claro e visualmente inativos.

Não usar cores semânticas de forma invertida: vermelho não é ação primária, verde não é cancelamento e azul não deve significar erro.

### Campos e controles

Padrão de inputs, selects, controles numéricos e áreas de texto:

- altura mínima 36 px;
- padding 5 x 10 px;
- fundo branco;
- texto `#081630`;
- borda `#C9D5E5`;
- raio 5 px;
- foco com borda `#0866F5`;
- seleção de texto com fundo primário.

Não remover o feedback de foco.

### Tabelas

Tabelas operacionais devem reutilizar `DataTable` sempre que possível.

Contrato visual atual:

```text
altura da linha:                 48 px
altura do cabeçalho:            48 px
largura mínima de coluna:       64 px
largura máx. de texto longo:   300 px
largura mínima de status:      190 px
padding de cálculo de célula:   32 px
padding de badge:               48 px
```

Regras:

- fundo branco;
- zebra com `#F1F3F6`;
- grid visível com `#C7D3E2`;
- cabeçalhos centralizados e bold;
- células centralizadas no padrão operacional atual;
- seleção com `#E8F2FF` sem inverter para texto branco;
- sem edição direta;
- seleção por linha;
- texto longo pode usar elide + tooltip;
- colunas de status não devem ser comprimidas abaixo do mínimo semântico;
- quando o conteúdo exceder a viewport, usar scroll horizontal em vez de destruir a legibilidade;
- não usar seletor CSS global de célula que sobrescreva as cores semânticas de linha.

### Estados e badges

Estados semânticos devem manter o padrão atual de fundo suave + texto/borda forte:

| Estado | Fundo | Texto/borda |
|---|---:|---:|
| Despachado / Concluído / Normal / OK / Ativa | `#EAF8EF` | `#11823B` |
| Finalizado | `#FFF6E6` | `#F07A00` |
| Destacando / Destaque / Em processo | `#E8F2FF` | `#0866F5` |
| Aguardando / Pendente | `#F2F4F7` | `#526078` |
| Atenção | `#FFF6E6` | `#D96800` |
| Atrasado / Crítico | `#FFF0F1` | `#E32636` |

O badge deve continuar compacto, arredondado e centralizado. Não representar status apenas por cor quando o texto já faz parte do componente.

O texto do badge e do estado vazio vem da camada de humanização
(`utils/systemState`), nunca do identificador cru do backend.

### Filtros de tela de cadastro (Wave 6E)

Pausas e Crachás usam a mesma barra (`components/RecordToolbar`): seletores +
busca + contagem do recorte + **Limpar filtros**. A regra é combinação simples,
não um filtro por campo. O recorte é aplicado sobre a lista já carregada — mudar
filtro não dispara consulta nova — e a seleção sobrevive à navegação da sessão
(`hooks/usePersistentFilters`). Filtro sem resultado mostra estado vazio
explicado, com a lista completa a um clique de distância.

### Ícones, logos e imagens

Os assets oficiais ficam em:

```text
assets/icons/
assets/branding/
```

Existe catálogo semântico em `assets` dentro de `web/src/config/assets.ts`.

Regras obrigatórias:

- reutilizar o SVG oficial correspondente antes de desenhar um ícone novo;
- preservar `viewBox`, proporção, sentido e identidade do asset;
- não editar o SVG em disco para mudar cor de um uso isolado;
- importar os assets pelo catálogo `web/src/config/assets.ts` ou helper equivalente;
- não substituir SVG oficial por emoji, ícone Unicode, Font Awesome, Material Icons ou asset externo sem autorização;
- não esticar imagem alterando sua proporção, salvo quando o componente existente fizer recorte intencional e validado;
- não deformar imagens de máquinas;
- não adicionar brilho, neon, sombra ou fundo decorativo aos ícones;
- manter ícones de uma mesma família com peso visual e escala equivalentes.

Branding oficial recortado:

```text
logo_gestor_pecas.png = 254 x 52
icone_perfil.png       = 60 x 60
```

Essas dimensões são validadas por teste.

### Telas e famílias de composição

Antes de alterar uma tela, identificar a família visual correspondente.

#### 1. Tela Inicial

Padrão:

- KPIs no topo em duas linhas;
- blocos de Últimas Movimentações e Tarefas Recentes;
- blocos de Alertas e Status;
- alinhamento de cabeçalhos de painéis;
- cards com altura equilibrada;
- sem scroll global da página em resoluções suportadas quando o layout atual já cabe.

#### 2. Tarefas e Cadastro

Padrão:

- toolbar/card de ações no topo;
- tabela como elemento principal;
- detalhes/ações secundárias abaixo quando aplicável;
- não deixar botões soltos fora do grid visual.

#### 3. Seleção de máquina

Padrão:

- cards grandes centralizados;
- duas opções na primeira linha e terceira centralizada;
- imagens de máquina em destaque;
- fundo geral limpo, sem painel decorativo adicional.

#### 4. Registro de máquina

Padrão:

- card de formulário central;
- forte hierarquia vertical;
- campo de OP como ação principal;
- status e fila abaixo;
- botão voltar no header.

#### 5. Consulta Operacional — seleção

Padrão:

- grade de `SelectionCard`;
- cada função representada por asset oficial;
- módulos novos devem seguir o mesmo sistema visual dos cards existentes.

#### 6. Consulta Operacional — visão geral

Padrão:

- KPIs compactos em duas linhas;
- alertas/status abaixo;
- controles secundários discretos;
- foco em leitura rápida de situação operacional.

#### 7. Consulta Operacional — tabelas

Padrão:

- filtros/ações no topo;
- tabela ocupando a maior parte da superfície útil;
- cores de linha e badge comunicam situação sem prejudicar leitura;
- histórico usa azul primário em ação de filtro/pesquisa quando aplicável.

#### 8. Relatórios — seleção

Padrão:

- dois cards grandes lado a lado;
- Movimentações associado ao roxo oficial;
- Tempo MES associado ao azul primário;
- muito espaço negativo controlado ao redor dos cards.

#### 9. Relatórios — conteúdo

Padrão:

- filtros/tabs discretos no topo;
- gráficos dentro de superfície branca;
- KPIs e tabelas usando os mesmos tokens do restante do sistema;
- não aplicar tema independente da biblioteca de gráficos que conflite com a UI.

### Gráficos

Gráficos Web devem parecer parte do sistema, não uma aplicação embutida com tema diferente.

Regras:

- fundo coerente com a superfície branca do card;
- títulos e labels legíveis;
- cores de série derivadas da paleta oficial quando houver correspondência semântica;
- evitar arco-íris de cores arbitrárias;
- quantidades de peças devem permanecer inteiras quando o dado for discreto;
- não remover eixos/labels necessários só para "limpar" o gráfico;
- respeitar o espaço do card e evitar corte de labels.

### Densidade e alinhamento

O design é compacto, porém não apertado.

Regras gerais:

- alinhar bordas de cards que pertencem à mesma coluna ou linha;
- manter alturas iguais em cards irmãos quando o padrão visual exigir;
- centralizar conteúdos de seleção e apontamento;
- em tabelas e dashboards, privilegiar uso da largura disponível;
- não criar grandes vazios por `stretch` mal posicionado;
- não encostar componentes nas bordas da página;
- não fazer correções locais que desalinharem a tela em outras resoluções.

### Regra para novos componentes e novas telas

Quando não existir mockup específico para uma nova funcionalidade:

1. identificar a família de tela existente mais próxima;
2. reutilizar layout, tokens e componentes compartilhados dessa família;
3. reutilizar `UI_COLORS`, `SPACING`, `RADII` e `DEFAULT_UI_FONT`;
4. reutilizar assets oficiais existentes sempre que semanticamente corretos;
5. criar o mínimo possível de novas constantes visuais;
6. se for necessário um novo padrão, centralizá-lo no design system em vez de espalhar stylesheet inline;
7. manter a nova tela visualmente indistinguível de uma tela que faria parte do conjunto original aprovado.

Não inventar design novo só porque não existe PNG da funcionalidade.

### Stylesheet e arquitetura visual

Preferência obrigatória:

- tokens em `web/src/styles/tokens.css`;
- stylesheet compartilhado em `web/src/styles/global.css`;
- componentes reutilizáveis em `web/src/components/`;
- composição das telas em `web/src/pages/` e `web/src/layouts/`.

Evitar:

- HEX repetido em dezenas de arquivos;
- `setStyleSheet` inline para componente reutilizável;
- regras globais que alterem widgets não relacionados;
- duplicar `SelectionCard`, `KpiCard` ou tabela com pequena diferença visual;
- valores mágicos sem relação com mockup, token ou necessidade responsiva.

Stylesheet inline é aceitável quando:

- o estado é realmente local/dinâmico;
- há justificativa semântica;
- não cria novo padrão visual paralelo.

### Mudanças visuais proibidas sem autorização explícita

Não fazer por iniciativa própria:

- redesenhar a interface;
- trocar paleta;
- trocar fonte;
- alterar logo;
- alterar espessura/estilo dos ícones oficiais;
- remover sidebar ou header;
- converter cards em layout sem borda;
- adicionar sombras/gradientes/neon;
- trocar tabelas por cards;
- trocar cards por tabelas;
- alterar ordem visual dos módulos principais;
- ocultar informação para "despoluir";
- reduzir controles operacionais importantes;
- mudar cor de status;
- alterar proporção das máquinas;
- usar assets `legacy` para substituir assets atuais;
- criar tema escuro;
- criar animações que atrasem operação ou modifiquem a leitura do estado;
- adicionar transparência que reduza contraste;
- substituir texto por ícone onde o mockup usa ambos.

### Fluxo obrigatório para qualquer tarefa visual

Antes de editar código de UI:

1. localizar a tela correspondente em `assets/screens/screens - atuais/`;
2. abrir e inspecionar visualmente o PNG;
3. identificar os SVGs/PNGs oficiais usados naquela tela;
4. ler os tokens em `web/src/styles/tokens.css`;
5. verificar o comportamento em `web/src/styles/`, `components/` e `pages/`;
6. localizar testes relevantes em `web/src/test/`;
7. medir geometria quando necessário, em vez de estimar "a olho";
8. modificar o menor número possível de componentes;
9. renderizar novamente e comparar com a referência;
10. validar também resoluções menores suportadas no navegador.

Uma IA não deve começar uma alteração visual relevante olhando apenas o componente React da tela.

### Regra de comparação visual

Ao comparar implementação com mockup, verificar no mínimo:

- largura da sidebar;
- altura do header;
- margem externa do conteúdo;
- posição do título;
- alinhamento dos cards;
- largura e altura de cards irmãos;
- distância entre cards;
- cor exata de fundos e bordas;
- raio de borda;
- tamanho e peso das fontes;
- tamanho, proporção e posição dos ícones;
- altura de inputs e botões;
- altura de linha e header de tabelas;
- alinhamento de tabela;
- cores de estados;
- comportamento de hover/foco/disabled quando relevante;
- overflow e clipping;
- presença indevida de scroll;
- comportamento em 1920x1080, 1600x900 e 1366x768.

Tolerância recomendada para elementos estruturais medidos na mesma escala: até aproximadamente 2 px quando houver arredondamento decorrente do fator responsivo. Cor de token e asset oficial não têm tolerância conceitual: devem ser os valores corretos.

### Validação visual automatizada

Quando uma alteração tocar o design, executar pelo menos:

```bash
cd web
npm test
npm run build
```

E, quando aplicável, também:

```bash
python -m unittest discover -s tests
```

Os testes de design já verificam, entre outros pontos:

- catálogo das telas atuais e legacy;
- dimensões dos PNGs oficiais;
- catálogo e validade dos SVGs;
- branding recortado;
- organização e dimensões de KPIs;
- geometria responsiva da sidebar e header;
- avatar, navegação, relógio e rodapé da sidebar;
- cards de seleção;
- tabelas, zebra, larguras, status e scroll;
- composição de relatórios e dashboards.

Não alterar testes para aceitar uma regressão visual. Se o design foi explicitamente alterado, atualizar teste e referência porque o contrato mudou, não porque o teste "atrapalha".

### Critério de pronto para tarefa visual

Uma tarefa visual só está pronta quando:

- a tela continua funcional;
- a regra de negócio não foi alterada;
- o mockup atual foi usado como referência;
- cores vêm dos tokens oficiais;
- fonte oficial foi preservada;
- assets oficiais foram reutilizados;
- proporções de imagens foram preservadas;
- componentes compartilhados foram reutilizados quando cabível;
- layout principal continua responsivo;
- não há clipping, sobreposição ou scroll indevido;
- os testes Web pertinentes passam;
- a tela foi comparada visualmente na resolução de referência;
- 1600x900 e 1366x768 foram verificadas quando a mudança for estrutural;
- qualquer divergência restante foi explicitamente informada no relatório final.

## Direção futura Web

A apresentação oficial do Gestor de Peças é Web, incluindo apontamento e visão dos gestores. Terminais de linha devem ser compatíveis com Raspberry Pi + Chromium e gestores/diretoria usam navegador em dispositivos autorizados. Todo código novo de domínio, analytics, contratos, repositories e services deve permanecer independente de React e FastAPI. Ver `docs/WEB_TARGET_ARCHITECTURE.md`.

## Regras visuais operacionais — refatoração v12

Estas regras complementam a identidade visual existente e valem para as telas de apontamento do operador. Elas não autorizam mudar a paleta oficial.

- Produção e Fila de Ordem devem usar cards com hierarquia fixa: OP/estado → operação → produto/descrição → quantidades/tempo → contexto do estado.
- Descrição longa deve usar elide/tooltip ou quebra controlada; nunca pode invadir quantidade, badge, botão ou borda.
- OP em parada deve mostrar, quando disponível, o motivo e o tempo decorrido da parada; cor vermelha sozinha não é informação suficiente.
- O apontamento de Parada deve oferecer busca incremental dos motivos e lista rolável, preservando motivo selecionado, comentário e contexto da OP/recurso.
- Painel sem conteúdo deve exibir empty state curto em vez de grande área branca sem explicação.
- Histórico de Produção deve permitir leitura por OP/produto/descrição e distinguir Aberto/Finalizado por texto e badge, não apenas por cor.
- O modo operador do Destaque segue `Início → Fim`; `Parada` é ocorrência contextual durante a execução. Os botões Início/Fim/Parada permanecem visíveis e habilitados; transição inválida deve gerar explicação, não botão morto.
- Detalhes do Destaque devem estruturar Início, Fim, estado/tempo e, quando houver parada, motivo e contador de parada. Não usar uma linha única separada por `|`.
- Finalização do Destaque exige confirmação específica com tarefa, OPs vinculadas e crachá do operador antes do registro do fim.
- A tabela de OPs do Destaque deve priorizar Código OP, Nome da Peça, Setor Destino e Quantidade; colunas técnicas não necessárias ao operador não devem ocupar espaço visual.
- A tela de Corte deve oferecer busca por tarefa/plano e, quando os dados existirem, material/nesting; cards devem separar cabeçalho, material/espessura/quantidade, nesting/tempos e ação.
- Mensagens de UI devem usar linguagem operacional. Não expor detalhes internos como PostgreSQL, workers ou sincronização técnica salvo em tela administrativa apropriada.
- Foco de layout: 1920×1080; validar resistência em 1600×900 e 1366×768 sem comprometer o 1080p.

## Telas gerenciais e informação de arquitetura

As telas gerenciais não devem exibir cards cuja informação principal seja
arquitetura, fonte, fallback, fórmula interna ou nome de tabela. Isso pertence à
documentação, a tooltip realmente necessário ou ao log.
