# Auditoria total de UI/UX/Design — Gestor de Peças (24/09/2026)

> Método: Impeccable critique + audit + detector, Playwright (Chromium 1.62) com screenshots e interação real, leitura de CSS/componentes para causa.
> Escopo: somente relatório — **nenhum código do repositório foi alterado**. Bugs funcionais aparecem como **FORA DO ESCOPO** (registrados, não corrigidos).
> Execução: agente único (pedido do usuário: "analise sozinho"); o critique do Impeccable prevê 2 avaliações isoladas — aqui foram feitas em sequência, pelo mesmo avaliador (**método degradado: single-agent**).
> Ambiente: harness TEST em memória (`tests/web_preview_api.py` na 8013; cópia com conta admin + chamadas/turnos em memória na 8014; `tests/andon_visual_preview.py` na 8011). Nenhum dado real tocado.
> Evidências: `docs/evidencias/auditoria_ui_2026-09-24/` (gitignored) — `matrix/` (177 arquivos), `flows/` (~130), `critique-A/`, `critique-B/`, `scripts/` (todos os scripts Playwright reproduzíveis).

---

## 1. Scores

| Score | Valor | Faixa |
|---|---|---|
| **Health (UX + técnico, média normalizada)** | **53 / 100** | Aceitável — trabalho significativo necessário |
| **Nielsen (10 heurísticas, 0–4)** | **20 / 40** | Aceitável (limite inferior) |
| **Técnico (Impeccable audit, 5 × 0–4)** | **11 / 20** | Aceitável |

### Nielsen

| # | Heurística | Nota | Justificativa principal |
|---|---|---|---|
| 1 | Visibilidade do estado do sistema | 2 | Parada/Retrabalho/Retomar sem feedback; 409 só na barra cinza; Andon sem "última atualização" |
| 2 | Correspondência com o mundo real | 2 | Vocabulário industrial bom; porém "Management View", "Retornar registrado com sucesso", "IagoDev/DEV —" |
| 3 | Controle e liberdade | 2 | Escape/Cancelar funcionam; Escape descarta edição sem aviso; sem desfazer |
| 4 | Consistência e padrões | 2 | Gestão é consistente entre si; operador/Andon/admin divergem; confirmação nativa × app × nenhuma |
| 5 | Prevenção de erros | 1 | Destrutivos sem confirmação, auto-desativação do admin, duplo envio na finalização, 999 peças sem aviso |
| 6 | Reconhecer em vez de lembrar | 3 | Recursos como botões, rótulos visíveis, sidebar clara |
| 7 | Flexibilidade e eficiência | 2 | Scanner + Enter carrega OP, presets de data; tabela sem ordenação, sem atalhos |
| 8 | Estética e minimalismo | 2 | Gestão limpa; Andon comprimido com metade da tela vazia; operador com dicas persistentes |
| 9 | Reconhecer/recuperar erros | 2 | Estados offline/500 com "Tentar novamente" bons; erro de OP genérico com UUID; login enganoso pós-desativação; export 500 baixa arquivo corrompido |
| 10 | Ajuda e documentação | 2 | Dicas inline existem, mas contraditórias (primeira peça) ou fora de hora (Setup) |

### Técnico (audit)

| Dimensão | Nota | Base |
|---|---|---|
| Acessibilidade | 2 | Botão primário do operador 1,87:1; FAB 2,76:1; foco perdido ao fechar diálogo; sem skip link; alvos < 44px no toque. Positivo: 0 controles sem nome, 0 inputs sem label, 1 h1 + main + nav em todas as rotas de gestão |
| Performance | 3 | LCP 0,2–0,56 s, CLS 0, INP 112 ms (workbench), 3 long tasks no workbench (servidor local — não representa rede real) |
| Responsivo | 2 | Gestão: 0 overflow horizontal em 37 rotas × 10 tamanhos. Andon ilegível ≤1366 e com scroll; portal do operador com 10px de overflow a 320px; modais de 707px em 768 |
| Theming/tokens | 2 | Cor bem tokenizada (100 de 124 hex em `tokens.css`), dark OK; tipografia/raio/breakpoints/z-index sem escala |
| Integridade/anti-padrões | 2 | 12 alertas do detector; `window.confirm` nativo; componente órfão; CSP bloqueando o próprio script |

---

## 2. Matriz de cobertura (rota × perfil × resolução/browser)

Legenda: ✅ testado com evidência · ⚠️ testado com achado relevante · ❌ NÃO TESTADO (motivo na §6)

| Área / rota | Perfil | 1024 | 1280 | 1366 | 1440 | 1600 | 1920 | 2560 | Zoom 150/200/400% (853/640/320) | Interação |
|---|---|---|---|---|---|---|---|---|---|---|
| /login | anônimo | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | vazio, senha errada, duplo clique, logout+voltar |
| Tela inicial (visão geral, setores, alertas) | gestor | ✅ | ✅ | ⚠️ FAB | ✅ | ✅ | ✅ | ✅ | ✅ | tabs, teclado, offline/500/lento, dark, forced-colors |
| Metas, Pausas, Chamadas | gestor/admin | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | CRUD, dirty state, destrutivos |
| Crachás, Turnos, Sistema, Cadastro | admin (gestor = 403) | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ | CRUD, destrutivos, Reiniciar build, auto-desativação |
| IA Industrial | gestor | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | estado "desabilitada" |
| Consulta Operacional (4 abas) | gestor | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | filtros |
| Produção (ordens, realizada, planejado×realizado) | gestor | ✅ | ✅ | ⚠️ tabela | ✅ | ✅ | ✅ | ✅ | ✅ | busca, paginação, presets, mais filtros, dark, forced-colors |
| Análises (8 abas, inclui Qualidade) | gestor | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | tabs por teclado, 500 |
| Auditoria (3 abas) | gestor | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Relatórios (5 abas) | gestor | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Exportar .xlsx (sucesso + 500) |
| Rastreabilidade (3 abas) | gestor | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| /andon | TV | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | evento de parada ao vivo, reduced motion, offline |
| /welding-management | TV | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ | rodízio (troca a cada ~10–20 s ✅) |
| Operador Dobra (workbench, primeira peça/Qualidade, cotas) | operador | ⚠️ | ✅ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ⚠️ 320 | fluxo completo, crachá, duplo clique, dark |
| Operador Corte | operador (toque) | ✅ | ✅ | ⚠️ alvos | ✅ | ✅ | ✅ | ✅ | ✅ | toque emulado |
| Operador Destaque | operador (toque) | ✅ | ✅ | ⚠️ alvos | ✅ | ✅ | ✅ | ✅ | ✅ | plano PROG-310, toque |
| Operador Solda | operador (toque) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | roteiro concluído, PDF |
| Dev Observatory (`/dev-observatory`) | dev (login próprio, credencial da fixture em instância TEST 8015) | ✅ | — | ✅ | — | — | ✅ | — | ⚠️ 320 | login vazio/errado/ok, teclado, falha de métricas |
| **Browsers** | — | Chromium ✅ · Firefox ❌ · WebKit ❌ (ver §6) | | | | | | | | |

> O `QualityPage.tsx` (operador) **não é importado por nenhuma rota** — a Qualidade do operador na prática é o diálogo de primeira peça (`QualityInspectionPage`) dentro do workbench, que foi testado. A Qualidade da gestão é `analises/qualidade` (coberta na matriz).

---

## 3. Achados

Formato: **ID · Prioridade · Status** — título
Rota · Persona · Fluxo/estado · Ambiente → Problema → Evidência → Arquivo/causa → Impacto → Recomendação.
Ambiente padrão: Chromium, zoom 100%, salvo indicação.

### P0

**AN-01 · P0 · CONFIRMADO** — Andon ilegível à distância
- `/andon` · TV/supervisor · estado normal e com parada · 1920×1080, 2560×1440, 1366, 1024.
- Problema: é um painel para ler a metros de distância, mas a **mediana do texto é 10px a 1920** (mínimo 7px), 13px a 2560 e **7px a 1366** (mínimo 6px). Os rótulos OEE/Disp./Perf./FTT têm 8px e os valores 11px.
- Evidência: `flows/andon_1920.png`, `flows/andon_1920_parada.png`, `flows/andon.json`, `matrix/gestor_andon_*.png`.
- Causa: `andon.css` (linhas ~232–662) usa `font-size` literais de 7–13px e aplica `scale()`/densidade para caber todos os setores numa tela; a grade não aproveita a altura (metade inferior de Corte/Solda/Pintura vazia a 1920).
- Impacto: o objetivo do Andon (entender o estado em 1–2 s, de longe) não é atingido; ninguém lê 8px a 3 m.
- Recomendação: para TV, tipografia mínima de ~24px no nome do recurso e ~32–48px no estado; layout por setor em rodízio (como já acontece na TV da Solda) em vez de todos os setores comprimidos; usar a altura disponível.

### P1

**AN-02 · P1 · CONFIRMADO** — Estados críticos do Andon cortados
- `/andon` · TV · parada/aguardando · 1920.
- Problema: as pílulas de estado truncam justamente o motivo: "AGUARDANDO MA…", "AGUARDANDO PO…", "TROCA DE FERRAMENTA" cortado. Os nomes de recurso também truncam ("Estaç…", "Torno Mecân…"). 5–56 elementos cortados conforme a resolução.
- Evidência: `flows/andon_1920_parada.png`, `flows/andon.json` (`clipped`).
- Causa: pílula de largura fixa + `text-overflow: ellipsis` num cabeçalho de card estreito.
- Impacto: o supervisor vê "vermelho" mas não o motivo; precisa ir até o posto.
- Recomendação: o motivo da parada deve ter uma linha própria, sem truncar; abreviar códigos, nunca a causa.

**AN-03 · P1 · CONFIRMADO** — Alarme sem saliência no Andon
- `/andon` · TV · parada injetada ao vivo (`/preview/andon/demo?acao=parada`) · 1920.
- Problema: uma parada tem o mesmo peso visual de um recurso produzindo: só uma pílula vermelha pequena e uma borda lateral de 3px. Não há escalonamento por duração nem destaque do crítico sobre o neutro.
- Evidência: `flows/andon_1920.png` × `flows/andon_1920_parada.png`.
- Causa: o card tem uma hierarquia única; o estado é só um acento (o detector também sinaliza `border-accent-on-rounded` em `andon.css`).
- Impacto: fere a consciência situacional (HMI: neutro/atenção/crítico devem ser distinguíveis na visão periférica).
- Recomendação: card inteiro em superfície de estado para parada/aguardando; cronômetro de parada grande; escalonamento (âmbar → vermelho) por tempo.

**OP-01 · P1 · CONFIRMADO** — Contraste dos botões primários do operador
- Portal do operador (todos os setores) · operador · estado inicial/OP carregada · 1366, claro e escuro.
- Problema:
  - "Iniciar atividade" tem **1,87:1** (branco sobre `rgb(66,216,90)`).
  - "Parada" tem 3,66:1.
  - "Retrabalho" (marrom) fica quase ilegível no escuro.
  - Os desabilitados usam pastel com texto branco ("Finalizar" amarelo-claro) e mal se distinguem de habilitados.
- Evidência: `flows/flows2_keyboard_filters_resilience_emulations_contrast.json` (`contrast_workbench_*`), `matrix/solda_operador_1366.png`, `flows/solda_a_carregada.png`.
- Causa: as cores de ação do workbench em `global.css` não usam pares de texto/fundo do token de estado.
- Impacto: é a ação mais frequente do chão de fábrica, lida sob luz forte e com luva; falha WCAG 1.4.3.
- Recomendação: texto escuro sobre verde (ou verde mais escuro); desabilitado = cinza neutro com ícone de cadeado ou motivo, e não a cor original desbotada.

**OP-02 · P1 · CONFIRMADO** — Estado do posto sem feedback após Parada, Retrabalho e Retomar
- Workbench Dobra · operador · Parada → Retomar; Retrabalho · 1366.
- Problema:
  - Depois de confirmar a parada não aparece mensagem nenhuma. O estado vive só num badge pequeno "Parada" no card da fila, e o elemento dominante da tela passa a ser o botão verde "Retomar".
  - Retrabalho: mesmo padrão, só o badge; o botão não mostra que está ativo.
  - Retomar: também sem feedback.
- Evidência: `flows/op6*`, `flows/op3_retrabalho.json`, `flows/op3_r_*`, `flows/op3_p_after.png`.
- Causa: `WorkbenchPage.tsx` só publica status em erro ou em algumas ações; o estado do apontamento não vira um "banner de estado" no topo.
- Impacto: o operador (ou quem assume o turno) não sabe em 1–2 s se o posto está parado. É consciência situacional.
- Recomendação: faixa de estado persistente no topo (PRODUZINDO / PARADO desde hh:mm — motivo / SETUP / RETRABALHO), com a cor de estado; toast de confirmação a cada ação.

**OP-03 · P1 · CONFIRMADO** — "Iniciar" habilitado quando o recurso já tem apontamento ativo
- Workbench Dobra · operador · recurso 1303 com OP-VISUAL-401 em processo, clicar Iniciar · 1366.
- Problema: o botão está habilitado; a rejeição (409 "Este recurso já possui um apontamento ativo…") aparece só na barra de status cinza neutra.
- Evidência: `flows/op2*.png`, `flows/op2.json`.
- Causa: a habilitação não considera o apontamento ativo do recurso; a barra de status não tem variante de erro.
- Impacto: tentativa e erro com saliência baixa; o operador pode achar que iniciou.
- Recomendação: desabilitar com o motivo visível ("Recurso já em produção: OP-…"), ou oferecer "Finalizar/Pausar a atual"; mensagens de erro na variante de alerta.

**OP-04 · P1 · CONFIRMADO** — Duplo envio em "Confirmar finalização"
- Workbench Dobra · operador · Finalizar → crachá 77 → duplo clique · 1366.
- Problema: saíram **2 POST** para `/v1/operator/actions`; o segundo foi recusado com 409 pelo backend. O botão não trava no primeiro clique.
- Evidência: `flows/op5.json`.
- Causa: o botão do diálogo não é desabilitado de forma síncrona antes do `await` (o login faz isso certo, com "Entrando…" desabilitado).
- Impacto: hoje o backend protege, mas a UI mostra um erro após o sucesso, o que confunde; outras ações sem idempotência ficariam expostas. A parte funcional fica **FORA DO ESCOPO**, e o problema de UI está CONFIRMADO.
- Recomendação: o padrão do login (estado "Enviando…" + disabled imediato) em todos os botões de confirmação.

**GE-01 · P1 · CONFIRMADO** — Ações destrutivas sem confirmação, e inconsistentes
- `/inicio/cadastro`, `/inicio/crachas`, `/inicio/chamadas`, `/inicio/sistema` · admin · clicar a ação · 1366.
- Problema: o clique executa na hora, sem confirmação, em:
  - "Desativar" (usuários e crachás);
  - "Remover responsável";
  - "Remover" contato (um contato foi de fato removido no TEST);
  - "Reiniciar build" (POST imediato que reconstrói o `web/dist` real).

  Só Pausas usa `window.confirm` nativo ("Remover a pausa "Almoço"? Esta ação não pode ser desfeita.").
- Evidência: `flows/flows3*`, `flows/t_*`, `flows/flows2_admin_forms.json` (`pausas_remover`).
- Causa: `UsersPage.tsx:188-201`, `PausesPage.tsx` (`confirm(`), `backend/api/routers/system.py:117-160` (`rebuild_frontend` sem etapa de confirmação no front).
- Impacto: perda de configuração com um clique; três padrões diferentes (nenhum, nativo, diálogo do app).
- Recomendação: um único `ConfirmDialog` do app para toda ação destrutiva, com o nome do objeto e a consequência; "Reiniciar build" com confirmação explícita.
- ⚠️ **Efeito colateral desta auditoria:** esse clique reconstruiu o `web/dist` (gitignored) a partir da working tree atual por volta das 13:56. O build terminou OK (`index.html` + 27 assets). Nada versionado mudou.

**GE-02 · P1 · CONFIRMADO** — Admin pode desativar a si mesmo e fica trancado, com mensagem enganosa
- `/inicio/cadastro` · admin · Desativar na própria linha · 1366.
- Problema: sem confirmação e sem guarda. No login seguinte a mensagem foi "Usuário ou senha inválidos." (ela descreve outra causa).
- Evidência: registrado nos fluxos admin (`flows2_admin_*`); reproduzido e restaurado reiniciando o harness.
- Causa: não há guarda no front (`UsersPage.tsx:196-198`) nem no back (`management.py:389-423`); o login não distingue "inativo" de "senha errada".
- Impacto: pode deixar o sistema sem administrador pela UI. A parte funcional/segurança fica FORA DO ESCOPO, e o risco de bloqueio é alto.
- Recomendação: impedir a auto-desativação (e a do último admin) e mostrar "Usuário inativo — procure o responsável".

**AX-01 · P1 · CONFIRMADO** — Falhas de contraste recorrentes (WCAG 1.4.3)
- Todas as telas · todos os perfis · claro e escuro · 1366.
- Problema:
  - FAB "Chamar": 2,76:1.
  - Badge de chamadas: 4,02:1 no claro e 2,75:1 no escuro.
  - "SITUAÇÃO DO DIA CORRENTE" (Recursos): 2,98:1 com 10px.
  - "Desenvolvido por"/"Powered by": 4,21:1 com 9–10px.
  - Pílulas "Em processo"/"Aguardando": 4,39–4,44:1.
- Evidência: `flows/flows2_keyboard_filters_resilience_emulations_contrast.json` (`contrast_*`).
- Causa: laranja e vermelho de marca usados como fundo de texto branco; `--text-2xs` de 10px com cor secundária.
- Impacto: legibilidade em monitor de fábrica; não conformidade AA.
- Recomendação: pares de token texto/fundo validados (≥4,5:1) e proibir texto secundário abaixo de 12px.

### P2

**OP-05 · P2 · CONFIRMADO** — Finalização sem confirmação de sucesso e com mensagem confusa
- Workbench Dobra · depois de "Confirmar finalização".
- Problema: não há mensagem de sucesso. Aparece "Etapa atual: não identificada. Esta operação não está disponível para Dobra neste posto."
- Evidência: `flows/op4*`, `flows/op5*`.
- Impacto: o operador fica em dúvida se finalizou.
- Recomendação: tela ou toast "OP-… finalizada: X boas, Y refugo" e limpar o contexto.

**OP-06 · P2 · CONFIRMADO** — O rótulo do botão principal muda de nome e o microcopy é técnico
- Workbench · o ciclo inteiro.
- Problema:
  - "Iniciar atividade" vira "Iniciar", depois "Retornar", depois "Retomar"; "Retornar" e "Retomar" convivem com sentidos parecidos.
  - Depois de liberar o lote aparece "Retornar registrado com sucesso."
- Evidência: `flows/op1*`–`op4*` (`buttons`).
- Causa: o rótulo deriva do código da ação, não da intenção do operador.
- Recomendação: um verbo por intenção (Iniciar / Retomar produção); mensagens em linguagem de chão de fábrica ("Lote liberado. Produção retomada.").

**OP-07 · P2 · CONFIRMADO** — Setup reabre o diálogo quando o posto já está em setup
- Workbench · Setup → Setup de novo.
- Problema: "Confirmar Setup" reaparece e a resposta é "Esta ação já está registrada: o apontamento já está em setup."; a mensagem global aparece duplicada dentro do modal.
- Evidência: `flows/op3_setup.json`, `flows/op3_*setup*`.
- Recomendação: mostrar o Setup como ativo (pressionado) e oferecer "Encerrar setup".

**OP-08 · P2 · CONFIRMADO** — Dica de Setup fora de contexto
- Workbench · qualquer estado.
- Problema: "Aponte o Setup para conferir a primeira peça…" fica visível mesmo com o botão Setup desabilitado.
- Recomendação: dicas condicionadas ao estado em que a ação é possível.

**OP-09 · P2 · CONFIRMADO** — Diálogo de primeira peça (Qualidade do operador)
- Workbench · primeira peça · 1366×768.
- Problema:
  - O diálogo tem 707px de altura em 768; "Liberar lote" encosta na borda e o FAB aparece atrás.
  - O foco não vai para o novo passo quando o passo muda.
  - O texto diz que "o sistema compara com a faixa… e decide a conformidade", mas existe um select manual de "Situação" (contradição).
  - "Medida" aceita "abc" sem feedback.
- Evidência: `flows/op4*.png`, `flows/op4.json`.
- Arquivo: `QualityInspectionPage.tsx:500`.
- Recomendação: rodapé de ações fixo dentro do diálogo; mover o foco para o título do passo; `inputmode="decimal"` com validação inline; decidir entre "automático" e "manual" e alinhar o texto a isso.

**OP-10 · P2 · CONFIRMADO / validação FORA DO ESCOPO** — Cadastro de cotas
- Workbench · primeira peça sem cotas.
- Problema:
  - Os placeholders "125,0" e "0,5" parecem valores preenchidos.
  - O campo "±" não tem label.
  - "Salvar cotas do produto" salvou com os campos vazios, e a tela seguinte mostra "PADRÃO ±" sem valores. Se o backend real valida: NÃO CONFIRMADO.
- Evidência: `flows/op4*`.
- Recomendação: placeholders como exemplo ("ex.: 125,0"), label "Tolerância (±mm)", salvar desabilitado com o motivo visível.

**OP-11 · P2 · CONFIRMADO** — Finalizar: bloqueio sem explicação e sem limite
- Diálogo Finalizar produção.
- Problema:
  - "Confirmar finalização" fica desabilitado sem dizer que falta o crachá.
  - Aceita 999 peças (planejado 12) sem aviso inline.
- Ponto positivo: o resumo (planejado/boas/saldo) é claro, e o crachá inválido mostra "Crachá não cadastrado ou inativo." inline.
- Recomendação: texto "Informe o crachá para confirmar"; aviso não bloqueante quando a quantidade passar do saldo.

**OP-12 · P2 · NÃO CONFIRMADO (backend real)** — OP inexistente dá erro genérico e sinais contraditórios
- Workbench · digitar uma OP que não existe.
- Problema: aparece "Não foi possível carregar os dados / Não foi possível concluir a operação" com um UUID de "Referência", enquanto a barra de status diz "Produção e fila atualizadas.".
- Motivo do NÃO CONFIRMADO: o fake devolve 500 para OP inexistente; o backend real provavelmente devolve 404. O defeito de UI (dois sinais contraditórios e o UUID exposto ao operador) vale nos dois casos.
- Evidência: `flows/op1*`, `flows/op1.json`.
- Recomendação: "OP XXXX não encontrada. Confira o código." e esconder a referência técnica (deixar só num "detalhes").

**OP-13 · P2 · CONFIRMADO** — Alvos de toque abaixo de 44px (WCAG 2.5.8 / luva)
- Corte, Destaque · toque emulado (`has_touch`) · 1366.
- Problema:
  - Corte: "Atualizar tarefas", "Histórico", "Registrar parada" e "Iniciar atividade" com 38px de altura.
  - Destaque: botões "i" com 22×22 e "Ver mais" com 32px.
  - Gestão: `table-link` com 16px de altura (9px em Setores e Inconsistências); toggle da sidebar com 22×44.
- Evidência: `flows/op7.json` (TARGETS_JS), `flows/op7_*`.
- Recomendação: mínimo de 44×44 no portal do operador (48 para uso com luva).

**OP-14 · P2 · CONFIRMADO** — Reflow a 320px no portal do operador
- Portal do operador · 320×256 (equivale a zoom de 400% sobre 1280).
- Problema: overflow horizontal de 10px. A gestão não tem esse problema.
- Evidência: `matrix/*_operador_320.png`, `matrix/dobra.json`.

**OP-15 · P2 · NÃO CONFIRMADO como defeito** — Solda: "Parada" habilitado com o roteiro concluído
- Operador Solda · OP-SOLDA-501 concluída · 1366.
- Problema: Iniciar, Finalizar e Retrabalho ficam desabilitados, mas Parada continua habilitada. A parada pode ser do recurso, não da OP (regra de negócio), por isso não confirmei como defeito. A mensagem "Roteiro concluído…" aparece só na barra neutra.
- Evidência: `flows/solda_a_carregada.png`, `flows/solda.json`.
- Recomendação: se a parada for do recurso, deixar isso visível no rótulo ("Parada do posto").

**AN-04 · P2 · CONFIRMADO** — Scroll vertical em painéis de TV
- `/andon` com 49px de scroll a 1366 e 97px a 1280; `/welding-management` com 244px a 1366 (fonte mínima de 9px).
- Evidência: `matrix/gestor_andon_1366.png`, `matrix/gestor_welding-management_1366.png`.
- Impacto: numa TV não há quem role a tela; o conteúdo abaixo da dobra some.

**AN-05 · P2 · CONFIRMADO** — Andon sem conexão apaga o quadro
- `/andon` · 15 s offline · 1920.
- Problema: o quadro inteiro é substituído por "Não foi possível carregar os dados / Tentar novamente". Não há relógio nem "última atualização" visível no estado normal.
- Evidência: `flows/andon_offline_15s.png`, `flows/andon2.json`.
- Impacto: uma oscilação de rede deixa a TV vazia, com um botão que ninguém vai clicar; no estado normal não dá para saber se os dados estão velhos.
- Recomendação: manter o último snapshot com a faixa "Sem conexão desde hh:mm — dados podem estar desatualizados", reconectar sozinho e mostrar um relógio ou carimbo de hora.

**GE-03 · P2 · CONFIRMADO** — Exportar Excel com erro do servidor baixa arquivo corrompido
- `/relatorios/*` · gestor · Exportar com a resposta 500 simulada via `route` · 1366.
- Problema: o navegador baixa `gestor_gerencial_2026-09-24.xlsx` contendo JSON de erro, sem nenhuma mensagem no app e sem indicação de carregamento. No sucesso, veio um .xlsx válido de 30 KB.
- Evidência: `flows/export.json`.
- Causa: `ReportsPages.tsx:51` usa `<a href download>` direto para a API.
- Recomendação: baixar via `fetch` + blob com estado "Gerando…" e erro inline.

**GE-04 · P2 · CONFIRMADO** — Formulários
- Novo usuário, crachá, contato, pausa e turno · admin.
- Problema:
  - "Salvar" fica desabilitado até o formulário estar válido, sem explicar o que falta e sem asterisco visível.
  - Login vazio usa a validação nativa do navegador, em inglês ("Please fill out this field.").
  - Senha errada: o foco vai para o body e a senha fica no campo.
- Evidência: `flows/flows2_admin_forms.json`, `flows/flows2_admin_login_flows.json`.
- Recomendação: marcar obrigatórios, validar inline em pt-BR, focar o campo com erro e limpar a senha.

**GE-05 · P2 · CONFIRMADO** — Estado sujo descartado sem aviso
- "Editar pausa" → alterar → Escape.
- Evidência: `flows3` (`dirty_escape`).
- Recomendação: "Descartar alterações?" quando o formulário estiver sujo.

**GE-06 · P2 · CONFIRMADO na UI / NÃO CONFIRMADO no servidor** — Turno invertido
- Turno 22:00–21:00 aceito pela UI, sem validação no cliente. O fake não valida, então o comportamento do servidor real ficou sem teste.
- Recomendação: validar no cliente ou tratar explicitamente o turno que cruza a meia-noite ("termina no dia seguinte").

**GE-07 · P2 · CONFIRMADO** — Páginas só de admin, abertas pelo gestor
- Cadastro, Crachás e Turnos · gestor.
- Problema: devolvem 403. Cadastro mostra um erro genérico com "Tentar novamente", e as outras ficam vazias, sem mensagem de permissão.
- Recomendação: esconder os itens do menu ou mostrar "Acesso restrito ao administrador".

**GE-08 · P2 · CONFIRMADO** — Densidade de ações por linha
- Problema: cada linha tem 3 ou 4 ações, com as destrutivas lado a lado com as seguras:
  - Pausas: Editar / Desativar / Remover.
  - Crachás: Editar / Desativar / Remover (ou Tornar) responsável.
  - Chamadas: Editar / Desativar / Tornar padrão / Remover.
- Recomendação: deixar Editar como ação primária e agrupar as outras num menu "⋯", com as destrutivas separadas.

**GE-09 · P2 · CONFIRMADO** — Tabela de Ordens
- `/producao/ordens` · gestor · 1366.
- Problema:
  - 14 colunas, com scroll horizontal interno (1291 de conteúdo para 1078 visíveis).
  - A coluna STATUS aparece cortada ("Em…").
  - Não há ordenação nem `aria-sort`, embora o `th` seja sticky.
- Evidência: `flows/emu_forced_producao_ordens.png`, `flows2` (`ordens_table`).
- Recomendação: fixar a coluna OP e a de status; colunas opcionais; ordenação por cabeçalho.

**GE-10 · P2 · CONFIRMADO** — Dois percentuais de progresso com bases diferentes
- `/producao/ordens` · gestor.
- Problema: o KPI "Peças boas" mostra "41,7% do planejado" (boas/planejado), enquanto a coluna PROGRESSO mostra 50% (atendida/planejado, com refugo incluído). Nenhum dos dois diz qual é a base.
- Evidência: `flows/emu_forced_producao_ordens.png`.
- Recomendação: rotular a base ("Atendido 50%", "Boas 41,7%").

**GE-11 · P2 · CONFIRMADO** — Diálogo "Novo contato"
- Problema: 17 campos em 707px de altura, grande espaço vazio na coluna esquerda e o placeholder do Telegram cortado.
- Evidência: `flows/flows2_admin_forms.json`, `flows/admf_inicio_chamadas_*`.

**AX-02 · P2 · CONFIRMADO** — Foco não volta ao gatilho quando o diálogo fecha (WCAG 2.4.3)
- Parada, Chamar, primeira peça e Qualidade.
- Causa: o `autoFocus` do input interno roda antes do `useEffect` do `useDialogFocus`. O elemento guardado passa a ser o input, que é desmontado ao fechar, e o foco cai no body.
- Arquivos: `StopReasonFields.tsx:41`, `ChamadaButton.tsx:211`, `WorkbenchPage.tsx:910`, `WorkbenchPage.tsx:1177`, `QualityPage.tsx:248`, `QualityInspectionPage.tsx:500`.
- Ponto positivo: o focus trap e o Escape funcionam.
- Recomendação: capturar `document.activeElement` antes de abrir (no handler), não no efeito.

**AX-03 · P2 · CONFIRMADO** — Foco invisível nos botões "Ver análise relacionada a…"
- Causa: `global.css:255-256` remove o outline.
- Recomendação: usar `:focus-visible` com o anel padrão.

**AX-04 · P2 · CONFIRMADO** — Não há skip link
- Problema: o Tab passa por todos os itens da sidebar antes de chegar ao conteúdo.
- Evidência: `flows2` (`skiplink: false`).

**AX-05 · P2 · CONFIRMADO** — Menu mobile (800px)
- Problema:
  - O foco não entra na gaveta.
  - O Escape não fecha.
  - O FAB "Chamar" fica acima do scrim (z-index 40 contra 27/30).
- Evidência: `flows/kbd_5_*`, `flows/kbd_6_*`.

**AX-06 · P2 · CONFIRMADO** — FAB "Chamar" fixo sobre o conteúdo
- Problema: a 1366 cobre "10h 35m" na visão geral; a 1366 e 1024 cobre o canto do card da fila no workbench; também aparece atrás de diálogos altos.
- Recomendação: reservar uma área para o FAB (`padding-bottom` no main) ou integrá-lo ao cabeçalho do operador.

**TE-01 · P2 · CONFIRMADO** — A CSP bloqueia o script de tema do próprio app
- Problema: o script inline anti-FOUC em `web/index.html` viola `script-src 'self'`. Isso gera um erro no console em todas as páginas, e quem usa tema escuro pode ver um piscar do tema claro na carga.
- Recomendação: mover o script para um arquivo `.js` estático ou usar hash/nonce. Não afrouxar a CSP.

**TE-02 · P2 · CONFIRMADO** — Drift do sistema de design (§5)

**IA-01 · P2 · CONFIRMADO** — Nomenclatura e arquitetura da navegação
- Problema:
  - Títulos em inglês: "Management View — Visão Geral/Setores/Alertas".
  - O mesmo lugar tem três nomes: "Tela inicial" no menu, "Visão Geral" na aba e "Management View" no título.
  - Erro de concordância: "Pausas automática".
  - Prefixos internos visíveis para quem usa o sistema: "DEV — Cadastro de usuários", "DEV — Crachás e responsáveis", "IagoDev — Turnos", "IagoDev — Sistema". Cadastro e Crachás ficam sob as abas de IagoDev.
  - "Chamadas" e "IA Industrial" aparecem sem prefixo de seção.
  - Não há breadcrumbs; a localização depende do prefixo do h1 e da aba ativa.
- Recomendação: um nome por lugar; seção "Administração" com Usuários, Crachás, Turnos, Pausas, Chamadas e Sistema; tirar "DEV" e "IagoDev" da UI de produção.

**DO-01 · P2 · CONFIRMADO** — Dev Observatory: texto miúdo e denso
- `/dev-observatory` · desenvolvedor · painel principal · 1024, 1366 e 1920.
- Problema:
  - Mediana de fonte de 11,5px e mínimo de 10px.
  - **361 de 548** elementos de texto têm menos de 12px.
  - Microrrótulos em caixa-alta, cards com borda lateral colorida (o anti-padrão `side-tab` de novo) e 939–1933px de rolagem vertical.
- Evidência: `flows/devobs_2_home.png`, `flows/devobs.json`.
- Causa: `app.css` próprio do observatório, sem os tokens do `web/`.
- Impacto: menor, porque é ferramenta interna, mas é a quarta linguagem visual do produto.

**DO-02 · P2 · CONFIRMADO** — Falha de um bloco apaga painéis sem explicar
- `/dev-observatory` · `GET /api/v1/dev-observatory/metrics?env=test` → 500. O 500 vem do banco fake do harness e é FORA DO ESCOPO.
- Problema: os painéis POSTGRESQL e PROCESSO DA API ficam vazios, sem mensagem dentro deles. O único aviso é um toast genérico, "Não foi possível concluir a operação.", no canto inferior direito, por cima de um card.
- Evidência: `flows/devobs_2_home.png`.
- Recomendação: estado de erro dentro do painel afetado ("Métricas indisponíveis — último valor hh:mm"), sem toast solto.

**DO-03 · P2 · CONFIRMADO** — Reflow a 320px no observatório
- Problema: 116px de overflow horizontal.
- Evidência: `flows/devobs_320.png`.

### P3

**DO-04 · P3 · CONFIRMADO** — Login e controles do observatório
- Problema:
  - Com os campos vazios, a validação é a nativa do navegador, em inglês.
  - Com senha errada, a mensagem "Usuário ou senha inválidos." aparece em vermelho pequeno, fora de `role=alert` (leitor de tela não anuncia). O foco vai para o body e a senha errada fica no campo.
  - 2 selects do cabeçalho (Ambiente observado, Atualização) não têm label associado.
  - Os estados vêm como códigos crus ("producao", "parada"), sem acento.
- Ponto positivo: login limpo e `autocomplete` correto (`username`, `current-password`).
- Evidência: `flows/devobs_0_login.png`, `flows/devobs_1_erro.png`.

**OP-16 · P3 · CONFIRMADO** — PDF com acessibilidade inconsistente
- Problema: o `aria-label` "PDF indisponível" não bate com o texto visível "PDF ↗", e o botão parece habilitado quando está desabilitado (Solda).
- Evidência: `flows/solda.json`.

**OP-17 · P3 · CONFIRMADO** — Cabeçalho e estrutura do operador
- Problema:
  - O placeholder do input da OP fica centralizado.
  - O nome da estação fica pequeno (≈11px), em maiúsculas e apagado no cabeçalho, justamente a informação que diz "onde estou".
  - O portal não tem h1.
  - "Powered by" tem 9px.
- Evidência: `matrix/solda_operador_1366.png`.

**OP-18 · P3 · CONFIRMADO** — Diálogo de parada
- Problema:
  - A busca sem resultado mostra "Nenhum motivo corresponde ao filtro informado." seguido de uma faixa vazia da lista.
  - As opções têm `role=option` sem `aria-selected`.
- Evidência: `flows/op6*`.

**OP-19 · P3 · CONFIRMADO** — Destaque: o rótulo "Ver OPs do plano PROG-310" aparece duplicado.

**GE-12 · P3 · CONFIRMADO** — Presets e abas
- Problema:
  - Os presets de data (Hoje, 7 dias…) não têm `aria-pressed` nem estado ativo visual.
  - As abas têm `role=tab`, mas as setas não navegam, porque são links `a.page-tab`.

**GE-13 · P3 · CONFIRMADO** — Dados
- Problema:
  - O zero aparece ora como "0", ora como "Sem registros", às vezes repetido em tabela e KPI.
  - Performance de 36,6% aparece sem meta nem limiar.
  - A barra de filtros tem 11 controles (carga cognitiva).

**IA-02 · P3 · CONFIRMADO** — "IA Industrial" é uma entrada de menu sem saída
- Problema: a tela diz "IA Industrial desabilitada / A disponibilidade desta função deve ser ativada pelo responsável pelo sistema.".
- Recomendação: esconder a entrada quando a função estiver desabilitada.

**AX-07 · P3 · CONFIRMADO** — forced-colors (alto contraste)
- Problema:
  - O item ativo da sidebar fica indistinguível.
  - As barras de progresso somem (o texto % continua).
  - O texto da marca vira contorno.
  - A pílula de status é cortada.
- Evidência: `flows/emu_forced_*.png`.

**TE-03 · P3 · CONFIRMADO** — Componente órfão
- `web/src/pages/operator/QualityPage.tsx` não é importado por nenhuma rota (código morto ou tela esquecida).

**AN-06 · P3 · CONFIRMADO** — TV sem controle de tela cheia
- Problema: não há controle de tela cheia (depende de F11 ou do quiosque) e não há região live (aceitável para TV).
- Ponto positivo: o reduced motion desliga a animação `andon-card-update`.

### Pontos positivos confirmados (evidência)
- **Gestão:**
  - 0 overflow horizontal em 37 rotas × 10 tamanhos.
  - 1 h1 + main + nav em todas as páginas.
  - 0 controles sem nome e 0 inputs sem label.
  - Ordem de tab lógica.
  - "Mais filtros" com `aria-expanded`.
- **Diálogos do app:** `aria-modal`, focus trap e Escape funcionam.
- **Estados de erro/offline/500:** consistentes (`DataState`) e com "Tentar novamente"; o spinner de carregamento tem texto.
- **Login:** trava o duplo envio corretamente ("Entrando…"). É o padrão a replicar.
- **Tema:** escuro funcional; reduced motion respeitado (0 animações).
- **Performance local:** LCP ≤ 0,56 s, CLS 0.
- **TV da Solda:** o rodízio funciona (o conteúdo muda a cada ~10–20 s).
- **Exportar:** o sucesso gera um .xlsx válido com nome datado.

---

## 4. Melhores e piores telas

| Melhores | Por quê |
|---|---|
| Produção › Ordens / Análises | Filtros consistentes, KPIs com explicação da base, tabela com cabeçalho fixo |
| Login | Duplo envio travado, mensagens claras |
| Estados de erro (DataState) | Uniformes e recuperáveis |

| Piores | Por quê |
|---|---|
| **/andon** | Ilegível à distância, estados críticos truncados, alarme sem saliência, apaga quando perde a conexão |
| **Workbench do operador** | Contraste do botão principal, estado do posto invisível, rótulos que mudam, duplo envio |
| **Administração (Cadastro/Crachás/Chamadas/Sistema)** | Destrutivos sem confirmação, auto-bloqueio do admin, nomes "DEV/IagoDev" |

---

## 5. Causas sistêmicas e drift

1. **Não há um componente de confirmação único**: cada tela decidiu sozinha (nenhuma confirmação, `window.confirm` nativo ou diálogo do app). Origina GE-01, GE-02 e GE-05.
2. **Não há um componente de botão assíncrono**: o login faz certo, os diálogos do operador não. Origina OP-04.
3. **A barra de status é o único canal de feedback do operador**, e ela é neutra e cinza tanto para sucesso quanto para erro. Origina OP-02, OP-03, OP-12 e OP-15.
4. **O Andon herdou a densidade de um dashboard de mesa**, em vez de ser desenhado para a distância. Origina AN-01 a AN-04.
5. **Tokens de cor bons, escalas soltas no resto:**
   - `font-size`: **40 valores distintos** (≈406 literais contra 33 usos de token; 66 declarações abaixo de 10px; `--text-2xs` = 10px).
   - `border-radius`: **20 valores distintos** (87 literais contra a escala 4/6/10/12/999).
   - Breakpoints: **20 valores distintos** (480, 580, 650, 800, 801, 860, 900, 940, 960, 1000, 1100, 1180, 1280, 1300, 1400, 1500, 1680, 1700, 2500…); 800/801 e 1280/1300 indicam remendos.
   - z-index: **12 valores ad hoc** (−1 a 1000; FAB 40 acima do scrim 27 e da sidebar 30).
   - 7 `!important`; 11 `style={{…}}` inline; `var(--space-*)` quase não usado.
   - Estilos do Andon parcialmente em `global.css`; `StatusBadge` diverge dos tokens de estado.
   - Detector do Impeccable: **12 alertas** (10 `side-tab` em `global.css`, 2 `border-accent-on-rounded` em `andon.css`).
   - Cor: 100 de 124 hex estão em `tokens.css` (bom); 24 hex + 36 `rgba()` literais fora dele.
6. **Nomenclatura sem dono**: inglês, prefixos internos e três nomes para o mesmo lugar (IA-01).

---

## 6. NÃO TESTADO (bloqueio, tentativas e o que falta)

| Item | Bloqueio | Tentativas | O que falta |
|---|---|---|---|
| Firefox e WebKit | **Não existe nenhum motor Firefox/WebKit na máquina.** Em `ms-playwright/` só há `chromium-1234`, e não há Firefox em `Program Files` nem Safari no Windows. O Edge instalado também é Chromium. | Verifiquei `ms-playwright/`, `Program Files/Mozilla Firefox`, o Edge e o Selenium 4.46 (instalado, mas o Selenium Manager baixaria o Firefox e o geckodriver). Toda alternativa exige **download**, que pela política de segurança desta sessão depende de autorização explícita. Perguntei e não houve autorização | Você autorizar `C:/Python314/python.exe -m playwright install firefox webkit` (~200 MB). Depois disso, rodar de novo `scripts/matrix.py` e `scripts/flows*.py` trocando `pw.chromium` por `pw.firefox`/`pw.webkit` |
| Dev Observatory com dados do REAL | A instância 8001 exige credencial real (não digitada) | **UI coberta** numa instância TEST (8015) com a credencial fictícia da fixture `tests/test_dev_observatory.py` e o painel REAL desligado; ver DO-01 a DO-04 | Ver o painel com o DSN do REAL configurado (somente leitura) para checar densidade com dados reais |
| Leitor de tela real (NVDA/Narrator) | O NVDA não está instalado. O Narrator existe (`System32/Narrator.exe`), mas a saída dele é áudio e só pode ser conduzida por controle de desktop (computer-use), com aprovação sua e em tela visível | Substituído pela árvore de acessibilidade do Chromium (nome/papel/valor, landmarks, headings, `aria-live`, `role=alert`) em todas as rotas. Com isso, confirmei os problemas de anúncio: o erro de login e o erro do observatório ficam fora de `role=alert`, e as opções de parada não têm `aria-selected` | Uma sessão com o Narrator mais o "Resumo de fala" (Narrador + Alt + X), com você autorizando o controle do desktop, ou o NVDA instalado |
| Toque físico e luva | Bloqueio físico: não há tela de toque nem luva no ambiente | Emulação `has_touch` com medição de alvos em todos os portais de operador (OP-13) | Teste presencial num tablet ou terminal de chão de fábrica, com luva |
| Validações do backend real (cotas vazias, turno invertido, OP inexistente = 404) | O harness é fake | Registradas como NÃO CONFIRMADO | Repetir na instância TEST real |

**Com esses itens em aberto, a cobertura não é 100%.** Em 24/09/2026 o usuário decidiu aceitar a auditoria assim: não autorizou o download dos browsers nem o controle do desktop para o Narrator.

---

## 7. Plano (ordem sugerida)

1. **Andon para TV** (AN-01 a AN-05): tipografia de distância, rodízio por setor, card de estado inteiro, snapshot quando offline. → `/impeccable adapt andon`, depois `/impeccable typeset andon`.
2. **Segurança de ação** (GE-01, GE-02, GE-05, OP-04): `ConfirmDialog` + `AsyncButton` únicos, e guarda contra auto-desativação. → `/impeccable harden`.
3. **Operador** (OP-01, OP-02, OP-03, OP-05, OP-06): contraste e desabilitado, faixa de estado do posto, feedback de cada ação, verbos estáveis. → `/impeccable clarify operador`, depois `/impeccable colorize operador`.
4. **Acessibilidade transversal** (AX-01 a AX-06, OP-13): pares de contraste, retorno de foco, skip link, gaveta mobile, FAB, alvos de 44px. → `/impeccable audit` de novo depois das correções.
5. **Navegação e nomes** (IA-01, IA-02, GE-07): seção Administração, sem DEV/IagoDev, um nome por lugar. → `/impeccable clarify`.
6. **Dados** (GE-09, GE-10, GE-13, GE-03): bases dos percentuais, tabela, zero, exportação com erro. → `/impeccable harden relatorios`.
7. **Drift** (TE-01, TE-02, TE-03): escalas de tipo, raio, breakpoints e z-index; CSP sem inline; remover o órfão. → `/impeccable extract`, depois `/impeccable document`.
8. Fechamento → `/impeccable polish`.

---

## 8. Um único MES profissional ou uma coleção de telas?

**Hoje é uma coleção de telas construídas em momentos diferentes, sobre uma base comum boa.**

A **gestão** já parece um produto: mesma sidebar, abas, barra de filtros, estados de erro e tokens de cor, sem overflow em nenhuma das 37 rotas. O **operador**, o **Andon**, a **administração** e o **Dev Observatory** (este com um `app.css` próprio) falam outras línguas:
- O operador tem cabeçalho azul-marinho próprio, feedback só numa barra cinza e verbos que mudam.
- O Andon usa a densidade de um dashboard de mesa numa TV.
- A administração tem três padrões de confirmação e prefixos de desenvolvedor.

As escalas tipográficas (40 tamanhos), de raio (20) e de breakpoint (20) mostram camadas sobrepostas de épocas diferentes. A unificação não exige redesenho: exige três componentes (confirmação, botão assíncrono, faixa de estado), um Andon pensado para distância e escalas fechadas de tipo, raio e breakpoint.

---

**Resposta final — Este frontend parece um único MES profissional e coerente ou uma coleção de telas construídas em momentos diferentes?**

Uma **coleção de telas construídas em momentos diferentes**, com quatro linguagens visuais: Gestão, Operador, Andon/TV e Dev Observatory. Elas compartilham uma boa base de tokens de cor e ainda não formam um MES único. A Gestão é o núcleo mais maduro e serve de referência para o resto.
