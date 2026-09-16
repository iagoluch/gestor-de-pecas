# Simulação de Fábrica Real — 15/09/2026 (turno 08:00–17:30, vigilância 06:00–22:00)

> Prompt para uma sessão dedicada. Cole inteiro. Ambiente **somente TESTE**.

---

## 0. Missão

Você vai operar o Gestor de Peças como uma fábrica de verdade durante um dia inteiro de produção, **terça-feira 15/09/2026**, e agir como QA industrial: produzir, errar, corrigir, chamar ajuda, refugar, retrabalhar, parar máquina, trocar OP e encerrar o turno. Tudo isso enquanto observa o sistema de fora pra achar bug, estado órfão, recurso "preso" e inconsistência entre telas.

Não é teste de carga nem demonstração. É um dia normal de chão de fábrica, com gente que se atrasa, digita crachá errado, clica duas vezes, esquece de finalizar e chama o líder quando a máquina quebra.

Parâmetros fixos:

| Item | Valor |
|---|---|
| Data virtual | 15/09/2026 (terça) |
| Janela de vigilância (virtual) | **06:00 → 22:00** (16h) |
| Turno produtivo | **08:00 → 17:30 exato**, com os intervalos que o calendário TESTE já define. **Sem hora extra**, nem antes nem depois. |
| Duração real | **8h** (`--duration 8h --factory-duration 16h` → velocidade derivada 2x) |
| Banco | `gestor_pecas_test` apenas. `gestor_pecas` é proibido (o preflight já aborta). |
| Seed | `20260915` (registrar no relatório) |
| Telegram de simulação | chat_id `6684124050` (temporário, ver §3 e §9) |

---

## 1. Regras invioláveis

1. **Nada toca o REAL.** Nem banco, nem `.env` do REAL, nem TOTVS de produção. A outbox TOTVS pode ser exercitada no TESTE, mas confirme antes que ela não aponta para endpoint de produção; se apontar, desligue o envio e registre isso como limitação.
2. **Snapshot antes de mudar, restauração no fim.** Tudo que for alterado só para a simulação (contatos de chamada, calendário, config) tem snapshot em `simulation_runs/<run>/snapshots/` antes da mudança e é restaurado na §9, **inclusive se a simulação abortar no meio** (use `try/finally` ou rotina de restauração idempotente que dá pra rodar sozinha).
3. **Não mascarar bug.** Se o sistema errar, registre com evidência (request/response, linha do banco, screenshot, horário virtual e real). Só corrija durante a execução se o bug impedir a simulação de continuar. Nesse caso corrija a causa raiz, rode os testes do módulo afetado e anote no relatório. O resto vira achado.
4. **Erro esperado ≠ bug.** Crachá inválido barrado, refugo sem autorizador recusado, apontamento fora do turno bloqueado: isso é o sistema funcionando. Classifique cada bloqueio como `esperado` ou `inesperado`.
5. **Não inventar regra de negócio.** Na dúvida sobre o comportamento certo, verifique código, testes e memórias do projeto. Se ainda assim não der pra decidir, registre como "comportamento a confirmar com o usuário" e siga.
6. **Não commitar.** Deixe as mudanças no working tree e liste os arquivos no relatório.
7. Invoque a skill `ponytail` no início (regra do projeto) e mantenha as mudanças de código mínimas.

---

## 2. Reaproveitar o simulador existente (não reescrever)

O pacote `simulacao/` já faz relógio virtual sincronizado com a API (`/system/simulation/clock`), provisionamento, ingestão de OPs, fábrica, detector, monitores, observatório, capturas visuais e relatório. A última execução válida foi `simulation_runs/20260913_113801` (ver `report_completo.md`). Parta daí.

Ajustes necessários antes de rodar:

1. **Nova config, sem sobrescrever a antiga:** `config/simulacao_fabrica_real_20260915.json`, derivada de `config/simulacao_industrial.json`, com:
   - `relogio.inicio_virtual = "2026-09-15T06:00:00"`.
   - **Postos da Solda atualizados para os 5 setores atuais** (`app/core/operator_sectors.py` → `WELDING_FAMILY_SECTORS`): Solda Aço (Estação 1..10, logins `estacao{n}aco`), Solda Alumínio (Alumínio 1..6, `estacao{n}alu`), Solda Robô (`robo1`), Proj. Ferramentaria (`projetos`, com seletor DISPEX/DISPG/SERVGE/DISPOS) e Protótipo (`prototipo`, PREMTG/SOLDA4). A config antiga ainda usa o setor "Solda" único com `sim_solda01..05`, que ficou desatualizado. Use uma amostra realista (ex.: 4 estações Aço, 2 Alumínio, Robô, Ferramentaria e Protótipo). Montagem não tem posto configurado: verifique se a tela trata bem o setor vazio, sem inventar recurso.
   - `fases` cobrindo 06:00–22:00: `pre_turno` (06:00, ocupação 0), `chegada` (07:40, ocupação ≈0.05, só login e preparação), `abertura` (08:00), `pico_manha`, `pre_intervalo`, `intervalo` (conforme calendário), `retorno`, `pico_tarde`, `fim_de_turno` (≈16:45, ocupação caindo), `pos_turno` (17:30, ocupação 0), `noite` (19:00, ocupação 0).
   - `checkpoints` **de hora em hora** de 06:00 a 22:00, mais `17:31`, `17:45` e `18:15` (encerramento do turno).
   - `processo_minutos` realistas: `simples [30,50]`, `comum [45,90]`, `complexa [90,180]`, `soldado [60,170]`, `pintura [40,120]`, `corte_nesting [10,35]`, `destaque [8,25]`, `setup [10,30]`, `retrabalho [15,45]`, `parada_curta [5,20]`, `parada_longa [25,70]`. OP de ponta a ponta, somando as etapas, fica **entre 30 min e 3 h**.
   - Lote de OP proporcional a um dia real, **não** 110+48. Calibre para que ≈70–85% da carga caiba no turno e sobre WIP legítimo no fim (OP em andamento que precisa ser interrompida corretamente às 17:30).
2. **Rodar com:** `--duration 8h --factory-duration 16h --seed 20260915 --config config/simulacao_fabrica_real_20260915.json` (adapte aos nomes reais da CLI do runner, sem digitar a velocidade: ela é derivada).
3. Se o simulador não tiver algum comportamento pedido abaixo (chamadas, autorização com chamada, janela pós-turno), **acrescente no próprio `simulacao/`** seguindo o padrão existente (`factory.py` para ações, `detector.py`/`monitors.py` para verificações, `report.py` para relatório).

---

## 3. Preparação do Telegram (temporária)

Contexto do código: `backend/api/routers/chamadas.py`. A chamada usa `TELEGRAM_BOT_TOKEN` e envia para `chamada_contatos.telegram_chat_id` do contato. Sem esse campo, cai em `GESTOR_CHAMADA_TELEGRAM_CHAT_ID`. Contato com `setores = '{}'` aparece em todos os setores.

1. **Preflight:** confirme que o `.env` do TESTE tem `TELEGRAM_BOT_TOKEN` preenchido. Mande uma chamada de teste e confirme `telegram_enabled`/`telegram_enviado = true`. Se o bot não entregar, **pare e reporte**: sem Telegram funcionando, metade do objetivo cai.
2. **Snapshot** de `chamada_contatos` inteira (`id, nome, funcao, ativo, padrao_gestao, telegram_chat_id, setores`) em `snapshots/chamada_contatos.json`.
3. Coloque `telegram_chat_id = '6684124050'` em **todos** os contatos existentes (ativos e inativos, para a restauração ser simétrica). Use a API admin `POST /api/v1/chamadas/admin/contatos` sempre que possível, para passar pelas mesmas validações da tela.
4. Para **cada setor de `GET /api/v1/chamadas/setores` que não tenha nenhum contato configurado explicitamente** (contato "todos os setores" não conta), crie um contato de simulação:
   - `nome = "SIM Líder <Setor>"`, `funcao = "Simulação 15/09/2026"`, `setores = ["<Setor>"]`, `telegram_chat_id = "6684124050"`, `ativo = true`.
   - Registre os `id`s criados em `snapshots/contatos_criados.json`.
5. Não mexa em `GESTOR_CHAMADA_TELEGRAM_CHAT_ID` nem no `.env`. O desvio temporário é só por contato, no banco TESTE.

---

## 4. Funcionalidade nova: chamar responsável na autorização de refugo e retrabalho

Hoje o operador só digita o crachá do responsável:
- refugo → `FinishDialog` em `web/src/pages/operator/WorkbenchPage.tsx` ("Crachá do responsável que autoriza o refugo");
- retrabalho / primeira peça bloqueada → diálogo "Setup e Qualidade" no mesmo arquivo ("Crachá do responsável" + "Autorizar e liberar");
- e o fluxo equivalente em `web/src/pages/operator/QualityPage.tsx`, se houver campo de autorização.

Implementar **antes** de iniciar a simulação:

1. Nesses pontos de autorização, adicionar **"Chamar responsável"**: um seletor com busca dos contatos de chamada filtrados pelo setor do posto (o mesmo `GET /api/v1/chamadas/contatos?setor=`), que dispara a chamada existente (`POST /api/v1/chamadas`).
2. **Reaproveite `web/src/components/ChamadaButton.tsx`.** Não duplique o formulário. Se faltar, estenda com props opcionais para pré-preencher `motivo` ("Qualidade") e `comentario` (OP, operação, recurso, quantidade de refugo ou motivo do retrabalho). Motivo e comentário continuam obrigatórios e editáveis, e o crachá do solicitante continua exigido (regra de 14/09/2026).
3. A chamada **não substitui** a autorização: o responsável ainda precisa informar o próprio crachá. O botão só avisa.
4. Mostrar ao operador que a chamada foi enviada (ou que falhou no Telegram) sem fechar o diálogo nem perder o que já foi digitado.
5. Testes: estender `web/src/test/chamada-button.test.tsx` e `web/src/test/operator.test.tsx` só nos casos novos. Rode apenas esses arquivos, mais o type-check do `web`.
6. Esta funcionalidade é **permanente**. O que volta ao normal no fim é só o chat do Telegram e os contatos de simulação.

---

## 5. Calendário e turno

1. Leia o calendário produtivo do TESTE para 15/09/2026 (terça). Se o turno não for **exatamente 08:00–17:30** ou se existir hora extra ativa nesse dia, faça snapshot e ajuste **só no TESTE**, para ficar 08:00–17:30 sem HE, mantendo os intervalos que o calendário já tem. Anote no relatório o que estava antes.
2. Confirme pela API (`/system/simulation/clock` e endpoints de calendário/OEE) que o sistema enxerga o mesmo turno antes das 06:00 virtuais.

---

## 6. Roteiro do dia (horário virtual)

### 06:00–08:00 — Antes do turno
- Nenhuma produção válida. Simule 2–4 operadores chegando cedo e tentando logar, abrir tela e **tentar iniciar apontamento antes das 08:00**. O esperado segue a regra do sistema (bloqueio ou tratamento fora do turno). Verifique no código qual é e classifique.
- Andon, TV, Capacidade e Solda gerencial: todos os recursos devem aparecer **sem demanda / fora do turno**, nunca "em produção" nem "parado" herdado de outro dia.
- Checagem de estado herdado: apontamento aberto, parada aberta, plano de Destaque em `inicio`, primeira peça pendente, retrabalho pendente de outros dias. Tudo vira achado com o id.

### 08:00–17:30 — Turno
Operação realista em todos os setores com posto (Corte com fila automática, Destaque, Dobra, Usinagem, Serra, Pintura com as 5 estações, os 5 setores de Solda):

- **Início**: atraso de entrada de 0–25 min em parte dos postos; primeira peça e setup exigidos onde a regra existe (lembrando que Solda e Pintura saem do portão da primeira peça, commit f8dc1c8).
- **Fluxo feliz** na maioria das OPs: iniciar → produzir → apontar parcial → finalizar com boas.
- **Erros humanos** (≈15% das ações, sem virar caos): crachá inexistente (`SIMINEX`), crachá inativo, crachá sem permissão de autorizar (`SIM00`), duplo clique em Iniciar/Finalizar, finalizar com quantidade acima do planejado, refugo sem autorizador, esquecer de adicionar operador, abrir a OP errada e trocar, posto errado confirmado pelo crachá (checar rótulo `Atual (Original)`), recarregar a página no meio do apontamento, dois operadores no mesmo posto.
- **Acertos** depois do erro: o operador corrige e segue. O sistema tem que aceitar a correção sem deixar lixo.
- **Paradas**: curtas e longas, planejadas e não planejadas, com motivo de catálogo. Pelo menos uma parada longa atravessando o intervalo e uma atravessando 17:30.
- **Qualidade**: primeira peça não conforme → retrabalho → autorização → liberação; inspeção com medida fora da cota; refugo com autorizador válido; retrabalho posterior; destino refugo.
- **Troca de OP**, finalização parcial, operador extra entrando e saindo.
- **Corte/Destaque**: consumir fila automática, completar ciclos de Destaque início→fim, tentar reabrir plano já iniciado.
- **Gestão em paralelo**: abrir periodicamente Andon (e rodízio da TV), Solda gerencial, Capacidade, OEE/calendário, Qualidade, Crachás, Histórico de chamadas, sininho de chamadas não vistas (marcar vistas), IA industrial (5–8 perguntas reais sobre o dia, checando se as respostas batem com o banco e não vazam dado técnico) e Dev Observatory (somente leitura: confirmar que gravação é recusada).

### Chamadas pelo botão "Chamar" — frequência calibrada
Pedido do usuário: **quer receber as chamadas no Telegram ao longo do dia, mas sem abuso. Nem rajada, nem evento raro.**

- Alvo: **uma chamada a cada 40–70 min virtuais durante o turno**, com intervalo mínimo de 25 min entre duas chamadas. Total do dia **≈ 9–13 chamadas** (no ritmo 2x, uma a cada 20–35 min reais).
- **Nenhuma** chamada fora de 08:00–17:30.
- Distribuição: variar setores e motivos (Manutenção, Qualidade, Falta de material, Ferramental, Outro). Pelo menos **3** dessas chamadas saem do novo "Chamar responsável" da §4 (2 de refugo, 1 de retrabalho). Pelo menos **1** vem da tela de gestão (com nome + e-mail manual).
- Cada chamada nasce de um **evento real da simulação** (parada de manutenção, primeira peça reprovada, falta de material que parou a OP). Nada de chamada solta.
- `comentario` sempre começa com `[SIMULAÇÃO 15/09]` e diz o que aconteceu (OP, recurso, sintoma), pra você identificar no celular.
- Erros de chamada entram **sem consumir essa cota** (são barrados antes do envio): crachá inválido no solicitante, motivo fora da lista, gestão sem e-mail. Confirme que nenhum deles gerou mensagem no Telegram.
- Ninguém responde. O operador segue: espera um tempo realista (5–20 min), então o responsável simulado "chega" e autoriza com o crachá autorizador, ou a parada continua e é encerrada depois.
- Para cada chamada, registrar: horário virtual/real, posto, motivo, contato, `telegram_enviado`, id no banco, e se o sininho da gestão atualizou em tempo real.

### 17:30 — Fim do turno (ponto crítico)
- **Sem hora extra.** Operação em andamento às 17:30 tem que ser interrompida pelo mecanismo de fim de turno (`mes/services/shift_boundary.py`, `tipo_interrupcao='fim_turno'`, `origem_automatica=true`). O detector já sabe que o evento retroativo de fechamento é legítimo.
- Simular 2–3 operadores **tentando continuar ou finalizar depois das 17:30** e 1 tentando iniciar OP nova às 17:40. Validar o comportamento contra a regra do sistema.
- Paradas abertas às 17:30: como ficam?

### 17:30–22:00 — Vigilância pós-turno (sem operação válida)
Agente de observação ativo, checando a cada 30 min virtuais (e nos checkpoints de hora cheia):
- **Nenhum recurso** em produção, setup, primeira peça, parada aberta ou "executando" no Andon, TV, Solda gerencial ou Capacidade.
- Nenhum apontamento sem fim, nenhum operador ainda vinculado a posto, nenhum plano de Destaque preso em `inicio`, nenhuma OP de Corte presa na fila como "em execução".
- OP em execução interrompida no fim do turno **não some** do Andon como "sem demanda" (regressão do commit fbde537).
- Consistência de números: boas + refugo por OP entre banco, tela do operador, Qualidade, OEE e relatório; saldo nunca negativo; "teto = planejado" respeitado.
- OEE e disponibilidade do dia fechados só com o tempo de 08:00–17:30 (menos intervalos). Nada contado entre 17:30 e 22:00.
- Outbox TOTVS: nada pendente com erro, nada duplicado, nada enviado para fora do TESTE.
- Recursos, memória, conexões PG e latência estáveis nas 4h30 sem carga (memória crescendo sem carga é achado).

---

## 7. O que observar o dia inteiro

Use `detector.py`/`monitors.py` existentes e acrescente só o que faltar:

- HTTP 5xx (limite 0), timeouts, latência p95 por endpoint, deadlock, conexões PG.
- Eventos fora de ordem (exceto o fechamento retroativo de turno já tratado), eventos órfãos, estado duplicado por duplo clique.
- Divergência de estado entre API, banco e tela (capturas visuais nos checkpoints de Andon, operador, Solda gerencial e Qualidade).
- Recurso "preso": estado ativo sem evento há mais de 2× a duração máxima da classe.
- Chamadas: toda chamada válida com `telegram_enviado=true`, toda inválida sem registro nem mensagem.
- Erros no console do navegador nas telas capturadas.

---

## 8. Entregáveis em `simulation_runs/<run>/`

1. `report.md` (resumo executivo) e `report_completo.md` (tudo, sem truncar, segmentado pelos checkpoints de hora em hora), nos moldes de `simulation_runs/20260913_113801/report_completo.md`.
2. Tabela **"Achados"** com: severidade (CRITICAL/ERROR/WARNING/INFO), classificação (bug do Gestor / bug do simulador / esperado / a confirmar), horário virtual, tela/endpoint, evidência, causa provável com arquivo:linha, e se foi corrigido.
3. Tabela **"Bloqueios esperados"** (erros humanos barrados corretamente).
4. Tabela **"Chamadas"** (todas as §6, com o status do Telegram).
5. Seção **"Estado às 17:30, 18:00, 20:00 e 22:00"** com a lista de recursos e seus estados, mostrando explicitamente que nada ficou para trás (ou o que ficou).
6. Seção **"Mudanças de código"**: a funcionalidade da §4, correções que foram necessárias, testes rodados e resultado.
7. Seção **"Restauração"**: prova de que a §9 foi feita (diff do snapshot contra o estado final).
8. Atualizar a memória do projeto com um arquivo novo `simulacao-fabrica-real-2026-09-15.md` (onde está o relatório, achados abertos, o que foi corrigido) e a linha no `MEMORY.md`.

---

## 9. Restauração obrigatória (sempre, mesmo em abort)

1. `chamada_contatos`: restaurar `telegram_chat_id` de **cada** contato pré-existente ao valor do snapshot (inclusive `NULL`), sem mexer nos outros campos.
2. Exportar as chamadas da simulação para `simulation_runs/<run>/chamadas.json` e só depois remover os **contatos criados** na §3.4 pelos ids registrados. As linhas de `chamadas` feitas durante a simulação ficam no TESTE como histórico (a FK vira `NULL` e nome/função continuam gravados); marque isso no relatório.
3. Calendário do TESTE: restaurar o snapshot da §5, se houve alteração.
4. Relógio da API de volta ao tempo real / simulação desligada.
5. Validar com `GET /api/v1/chamadas/admin/contatos` + consulta ao banco que o estado bate **exatamente** com o snapshot (fora os contatos criados, que não existem mais). Registrar o diff vazio no relatório.
6. Mandar **uma última mensagem** pelo fluxo normal da gestão, antes de restaurar o chat, com `[SIMULAÇÃO 15/09] Encerrada — relatório em simulation_runs/<run>/`, para você saber que acabou. Ela conta dentro da cota de chamadas.

---

## 10. Critérios de pronto

- [ ] Rodou 06:00→22:00 virtual completo (ou abortou com causa documentada e restauração feita).
- [ ] Turno efetivo exatamente 08:00–17:30, zero minuto de hora extra contabilizado.
- [ ] Todos os setores com posto operaram, incluindo os 5 setores de Solda.
- [ ] OPs com duração de 30 min a 3 h, com WIP legítimo interrompido às 17:30.
- [ ] Erros humanos e acertos exercitados, com os bloqueios classificados.
- [ ] 9–13 chamadas recebidas no Telegram durante o turno, espaçadas, ≥3 via "Chamar responsável" e ≥1 da gestão.
- [ ] Funcionalidade "Chamar responsável" em refugo e retrabalho implementada e testada.
- [ ] Pós-turno sem recurso preso, ou cada caso listado como achado com evidência.
- [ ] 0 HTTP 5xx não explicado.
- [ ] Relatórios gerados, restauração provada com diff vazio, memória atualizada.

## 11. Integração Protheus ↔ Gestor: OP entrando e OP saindo finalizada

Objetivo: provar, com OP **real do Protheus TESTE** (filial `010004`), o ciclo completo. A OP chega ao Gestor pelo pull sob demanda, é produzida no chão de fábrica simulado, e o Gestor devolve ao Protheus cada apontamento, parada, refugo e, no fim, o **marco terminal** que finaliza a OP, com datas e quantidades corretas.

### 11.1 Regras específicas desta parte

1. **Só Protheus TESTE.** Antes de tudo, confirme pelo `.env` do TESTE e por uma chamada de leitura que o WSPCP e o GPOPSYNC (`WSRESTFUL gestorpecaspo`, porta `:1467`) apontam para o ambiente de teste (`CSED4J_DEV`). Se houver qualquer dúvida de que é produção, **não envie nada** e reporte.
2. **Gravação no Protheus não tem volta pelo Gestor.** SD3/SH6/C2_QUJE gravados ficam lá. Por isso:
   - use **no máximo 5 OPs reais**, escolhidas de propósito;
   - nunca tente estornar pelo Gestor;
   - anote cada envio para o usuário conferir depois.
3. **As OPs sintéticas da simulação (prefixo `SOAK`) não podem chegar ao Protheus.** Verifique no código (`mes/integrations/totvs/outbound_enqueue.py`) se o Gestor enfileira outbox para OP sem origem TOTVS.
   - Se enfileirar, isso já é um **achado**: geraria rejeição em massa e spam no Telegram de erro da outbox.
   - Nesse caso, pare antes da abertura do turno e reporte, sem gambiarra no backend.
4. Flags que precisam estar ligadas no TESTE (confirme, não altere às escondidas): `GESTOR_TOTVS_ENABLED`, `GESTOR_TOTVS_OUTBOX_ENABLED`, `GESTOR_TOTVS_OUTBOX_WORKER_ENABLED`, `GESTOR_TOTVS_OUTBOX_TERMINAL_ENABLED`. Anote o valor de `GESTOR_TOTVS_OUTBOX_TELEGRAM_CHAT_ID`. Se estiver vazio, a notificação de rejeição não vai chegar: registre como limitação e não mexa no `.env`.
5. **Datas × relógio virtual (ponto crítico).** Os apontamentos saem com o horário virtual da simulação (`StartReportDateTime`, `EndReportDateTime`, `ReportDateTime`). Compare esse horário com a hora real do servidor Protheus antes de cada envio.
   - Se o horário virtual estiver **no futuro** em relação ao Protheus, não falsifique a data.
   - Faça os eventos das OPs reais numa janela em que virtual ≤ real. Se ainda assim o Protheus rejeitar, registre o texto exato da rejeição como achado.

### 11.2 Escolha das OPs reais

1. No início da sessão, **peça ao usuário** de 3 a 5 números de OP abertas no Protheus TESTE, com roteiro e sem apontamento.
2. Se não houver resposta em 10 min reais, levante candidatas locais (inbox/catálogo TOTVS do `gestor_pecas_test`). Use só as que o GPOPSYNC confirmar como **abertas** e **sem apontamento**.
3. Busque cobrir:
   - uma OP de **uma operação** apontável + marco terminal 99;
   - uma OP **multissetor** (ex.: Corte → Usinagem → 99);
   - uma OP que passe por **Destaque** (recurso que não existe no TOTVS);
   - uma OP para o caso de **finalização parcial** (Gestor conclui menos que o planejado).
4. Registre de cada uma: produto, modelo (`B1_ZMODELO`), planejado, roteiro (operação/recurso/ActivityID), filial e status PCP.

### 11.3 Entrada: OP vindo do Protheus para o Gestor

1. **Pull sob demanda pela tela.** O operador digita uma OP que ainda não existe localmente, o que dispara `POST /api/v1/operator/operations/{op}/sync`. Valide a cadeia `OrderProvisioningService → ProductionOrderOnDemandSyncService → GPOPSYNC → MATI650 → ingestão → PostgreSQL`.
   - A OP deve aparecer **no setor certo**, com produto, descrição, modelo, quantidade, datas e roteiro iguais ao Protheus.
   - O marco 99 deve ficar invisível ao operador (`ativo = FALSE`, `marco_terminal = TRUE`).
2. **Idempotência.** A segunda consulta da mesma OP tem que ser local, **sem nenhuma chamada ao ERP**. Prove pelo log/contagem de requests.
3. **Erros de entrada** (operador errando):
   - OP inexistente no Protheus → mensagem amigável, sem travar e sem repetir a chamada a cada tecla;
   - OP digitada com espaço/zeros a menos → normalização correta;
   - OP sem roteiro → `sem_roteiro`/`found=false`, sem inventar operação.
4. **Duas telas pedindo a mesma OP ao mesmo tempo:** só uma solicitação de sync e nenhuma duplicata em `catalogo_pcp_ops`/`catalogo_operacoes_op`.
5. **Alteração no Protheus (opcional, depende do usuário).** Se o usuário alterar quantidade ou data de uma das OPs no Protheus durante o dia, verifique se o Gestor reflete a mudança e em que momento. Se o Gestor não atualizar, registre como achado (requisito da reunião de 14/09: "atualizar conforme o TOTVS muda").

### 11.4 Saída: Gestor devolvendo ao Protheus

Para cada OP real, produzir no fluxo normal do operador e acompanhar a outbox até `SENT`:

| Evento no Gestor | Mensagem esperada | Conferir |
|---|---|---|
| Apontamento parcial | `ProductionAppointment` | `ReportQuantity`, `ApprovedQuantity`, `ScrapQuantity`, `StartReportDateTime`/`EndReportDateTime`, `ActivityCode`/`MachineCode`/`ActivityID` exatamente como recebidos |
| Refugo autorizado | `ProductionAppointment` com bloco de perda | `WasteCode` homologado (`RP`) + quantidade |
| Parada com motivo | `StopReport` | `StopReasonCode` homologado (`0010`/`0018`), início/fim, `ReportDateTime` |
| Finalização da operação | `ProductionAppointment` | quantidades acumuladas corretas, sem contar duas vezes |
| Última operação concluída | **Marco terminal** (`production_appointment_terminal`) | `ActivityCode 99`, `MachineCode ALMOX4`, `CloseOperation=true`, `ApprovedQuantity` = boas **só da última operação produtiva**, refugo fora, datas de início/fim da execução |

Casos obrigatórios:

1. **Terminal nunca prematuro.** Com operação ainda aberta, o terminal **não** pode ser emitido (o mapper lista as operações pendentes). Só depois da última operação finalizada.
2. **Finalização parcial:** Gestor conclui menos que o planejado → terminal com a quantidade **menor**, sem completar pelo saldo. Registrar o que o Protheus fez (encerramento parcial × total).
3. **Boa acima do planejado** → recusada com mensagem explícita, sem truncar.
4. **Retrabalho** → item **bloqueado** na outbox, não enviado (decisão de contrato). Confirmar que não trava o resto da OP.
5. **Destaque** (sem recurso no TOTVS) → não gera envio próprio. A produção é consolidada na próxima etapa que o TOTVS reconhece.
6. **Apontamento com menos de 1 minuto** numa OP real. Regra do Protheus; o Gestor **não tem** essa validação hoje. Registrar exatamente como o Protheus respondeu e como a outbox classificou (`FUNCTIONAL` sem retry, ou outra coisa). É achado de qualquer forma.
7. **Duplo clique em Finalizar** → uma única obrigação na outbox (mesma `idempotency_key`), nenhum SD3 duplicado.
8. **Queda no meio do envio:**
   - reinicie o backend enquanto um item estiver `SENDING`;
   - ele tem que voltar sozinho por expiração de lease, com a **mesma** chave, sem duplicar no Protheus.
   - Um único reinício controlado, fora dos checkpoints visuais.
9. **OP já totalizada no Protheus** (`A680OPTOT`), se alguma OP escolhida permitir o cenário → classificada como `FUNCTIONAL`, sem retry infinito, e **notificação no Telegram** de erro da outbox.
10. **Fim de turno às 17:30 com OP real em andamento:**
    - a interrupção automática não pode emitir terminal;
    - a obrigação parcial (se houver) sai com o horário de corte do turno, não com o horário em que o worker rodou.

### 11.5 Reconciliação: o Protheus finalizou mesmo?

1. Não há acesso ao banco Protheus. A prova vem de:
   - (a) ACK/`InternalId` de cada item `SENT`;
   - (b) **novo pull via GPOPSYNC** da OP depois do terminal, conferindo `ReportQuantity` e `StatusOrderType` do `ProductionOrder` devolvido (o `report_quantity` fica no `payload_raw` da inbox).
2. Monte, por OP, a **linha do tempo completa**: pull de entrada → cada evento do operador → cada item da outbox (tipo, XML enviado salvo em arquivo, resposta, tentativas, status, InternalId) → re-pull final.
3. Quantidades batendo em quatro lugares: `eventos_quantidade_producao` (Gestor), XML enviado, `ProductionOrder` re-puxado e telas (operador/Qualidade/OEE).
4. **Às 22:00**: nenhuma obrigação da outbox das OPs reais em `PENDING`, `RETRY` ou `SENDING`. `ERROR` só nos casos provocados de propósito (11.4.6 e 11.4.9), cada um explicado.

### 11.6 Entregáveis adicionais

- Seção **"Integração Protheus"** no `report_completo.md` com a linha do tempo de cada OP real e os XMLs em `simulation_runs/<run>/totvs/<OP>/`.
- Tabela de rejeições do Protheus com o texto literal e a classificação da outbox.
- **Checklist para o usuário conferir manualmente no Protheus TESTE**, por OP: `C2_QUJE`, `C2_DATRF`, legenda da OP, movimentos SD3 e apontamentos SH6 esperados (quantidade e data de cada um). O agente não tem como conferir isso sozinho.
- Deixar claro no relatório que **os envios ao Protheus TESTE não são revertidos** pela restauração da §9.

Critérios de pronto adicionais:
- [ ] ≥3 OPs reais puxadas via GPOPSYNC pela tela do operador, com idempotência provada.
- [ ] ≥1 OP finalizada no Protheus pelo marco terminal, confirmada pelo re-pull.
- [ ] Casos 11.4.1 a 11.4.8 executados e classificados (11.4.9 se houver OP viável).
- [ ] Zero OP sintética enviada ao Protheus.
- [ ] Outbox das OPs reais sem pendência às 22:00.























