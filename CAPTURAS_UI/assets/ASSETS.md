# Assets reais do frontend

Coleta feita em 08/10/2026 a partir das referências estáticas atuais do frontend. A origem canônica é `web/src/config/assets.ts`; ela é consumida pelo shell gerencial, pelo shell do operador, pela navegação e pelos cards de recurso. As folhas de estilo entram por `web/src/main.tsx`.

Foram excluídos screenshots históricos e arquivos sem referência atual. Os binários foram copiados sem conversão para preservar conteúdo e metadados.

| Origem no repositório | Destino nesta captura | Finalidade no produto |
| --- | --- | --- |
| `assets/branding/logo_gestor_pecas.png` | `logos/logo_gestor_pecas.png` | Marca no shell gerencial. |
| `assets/operator_mockup/logo_operator.png` | `logos/logo_operator.png` | Marca no cabeçalho do posto do operador. |
| `assets/branding/icone_perfil.png` | `imagens/icone_perfil.png` | Avatar do shell gerencial. |
| `assets/operator_mockup/profile_operator_transparent.png` | `imagens/profile_operator_transparent.png` | Avatar do posto do operador. |
| `assets/web/navigation/{home,operations,production,analytics,audit,reports,traceability}.png` | `icones/` | Ícones das seções da navegação gerencial. |
| `assets/web/navigation/{panels,manufacturing,quality,dev}.svg` | `icones/` | Ícones das seções gerenciais em SVG. |
| `assets/operator_mockup/nav_{destaque,dobra,usinagem,serra,corte,pintura,solda}_transparent.png` | `icones/` | Ícones das abas por setor no posto. |
| `assets/icons/{Pesquisa,Relógio,Lixeira}.svg` | `icones/` | Ações e relógio compartilhados nos shells. |
| `assets/icons/{Dobra_1303,Dobra_2204,Logo_Dobra,Logo_Usinagem,Logo_Serra,Logo_Corte,Recurso_Preparacao,Recurso_Pintura,Recurso_Inspecao,Recurso_Dispositivo,Recurso_Servicos,Recurso_PreMontagem,Recurso_Solda}.svg` | `icones/` | Identidade de setores e fallback vetorial de recursos. |
| `assets/icons/{Dobra_Gasparini,Serra_SFG-330,Serra_S4220,Serra_SFHA-10,Usinagem_RomiD1000,Usinagem_Eurostec,Usinagem_RomiGL350M,Usinagem_FresadoraFTV31,Usinagem_TornoMecanico,Corte_TerraBlade4,Corte_Ensis3015,Pintura_Jato,Pintura_Secagem}.{png,jpg}` | `imagens/` | Imagens de equipamentos para cards e posto do operador. |
| `web/src/styles/{tokens,global,ai,andon,standard-time,quality-templates}.css` | `estilos/` | Tokens, layout geral e estilos por tela. |
| `web/src/{main.tsx,config/assets.ts,layouts/AppShell.tsx,layouts/OperatorShell.tsx,components/PageFrame.tsx,components/FactoryMap.tsx}` | `estilos/componentes_referencia/` | Referência de carregamento de estilos, resolução dos assets e aplicação visual nos shells, páginas e mapa. |

## Fontes

`fontes/` não contém binário porque não há `@font-face` nem fonte web referenciada. `tokens.css` usa a pilha de fontes do sistema `-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `Roboto`, `Helvetica Neue`, `Arial` e `sans-serif`; `ai.css` usa `Consolas` como monoespaçada local.

## Integridade e duplicatas

Foram calculados SHA-256 para os 63 arquivos copiados (51 assets visuais, 6 CSS e 6 referências de componente). Não há dois arquivos copiados com o mesmo SHA-256, portanto não houve cópia redundante por conteúdo.

Há apenas reuso lógico no código-fonte: `audit.png` também representa a aba Qualidade do operador, e `nav_solda_transparent.png` representa Solda Aço, Solda Alumínio, Solda Robô, Proj. Ferramentaria e Protótipo. Cada arquivo físico foi preservado uma única vez.
