# STATUS ATUAL — Gestor de Peças

**Atualizado em:** 23/09/2026 (fechamento da auditoria F1–F21 — ver §2.37).
**Propósito:** o `ROADMAP.md` é o documento canônico de direção, mas seu
corpo principal (seção 5) parou de ser editado em 11/09/2026 (Wave 6E). Este
arquivo cobre **o que aconteceu depois disso**, para qualquer agente (Codex,
Claude ou outro) começar uma sessão sabendo o estado real do repositório sem
precisar reconstruir isso a partir de commits soltos ou de memória de outra
ferramenta.

Ordem de leitura recomendada para contexto rápido: `AGENTS.md` → `ROADMAP.md`
(seção 5, "Próxima ação concreta") → **este arquivo** → o `git log` desde o
commit `4a60564`.

### Atualização de auditoria — 23/09/2026

- O posto do operador passou a usar uma barra superior enxuta em todas as
  telas compartilhadas por `OperatorShell`: logo, data/hora, setor e recurso
  selecionado no centro e ações compactas. Em Solda, o recurso é identificado
  como **Estação**; nos demais postos, como **Máquina**. A troca permanece no
  próprio identificador central, sem restaurar a sidebar.
- A outbox TOTVS agora preserva a ordem causal por OP: evento em `RETRY`,
  `SENDING` ou `ERROR` bloqueia qualquer posterior da mesma OP; somente
  `SENT` libera a sequência. A migration 46 normaliza itens anteriores para
  a chave da OP e cria o índice de suporte. O fato canônico continua ligado ao
  item por `canonical_event_id` para idempotência e reconstrução.
- A exclusividade de recurso agora é conferida em qualquer entrada para estado
  ocupante, inclusive `Aguardando → Parada`. A trava e a comparação usam a
  identidade canônica do recurso, reconhecendo aliases oficiais como `LASER1`
  e `Laser Ensis 3015`.
- Exceções de recurso divergente e etapa anterior pendente exigem agora um
  crachá com a designação já canônica de responsável (`autorizador_retrabalho`);
  um crachá meramente ativo não autoriza a exceção.
- Sessões principais agora carregam a versão de sessão do usuário; mudança de
  senha, nível ou ativação incrementa essa versão e revoga tokens anteriores.
  A migration 47 adiciona a coluna e mantém tokens antigos fora do acesso até
  um novo login.
- O atraso progressivo do login agora persiste por chave de cliente e usuário
  no PostgreSQL, compartilhando o contador entre workers e sobrevivendo a
  reinícios; a janela expira o contador sem bloquear o operador. A migration
  48 cria `login_throttle`, com teste de persistência e expiração.
- Os consumidores de turno deixaram de reconstruir `08:00–17:30` por conta
  própria: `parametros_turno` agora alimenta a mesma instância de regras usada
  pelo calendário, pela auditoria e pelo contrato de capabilities da UI. O
  fallback global de calendário e os limites de auditoria acompanham a edição
  administrativa sem reinício.
- O calendário produtivo por recurso ganhou escritores administrativos reais:
  admin pode cadastrar calendário, turnos semanais e vínculo recurso-calendário
  por `/management/productive-calendars` e `/management/resource-calendars`,
  com CSRF e publicação de invalidação. O caminho deixou de depender só de
  seeds/testes.

Quando este arquivo crescer demais ou a próxima wave fechar, seu conteúdo deve
ser incorporado ao `ROADMAP.md` (por quem estiver trabalhando no projeto) e
este arquivo pode ser esvaziado para a wave seguinte — não deixar os dois
divergirem por muito tempo.

---

## 1. O que mudou desde a Wave 6E (11/09) até hoje (15/09)

### 1.1 Solda deixou de ser um setor único — agora são 5 (13–14/09/2026)

Especificação fechada com o usuário em 14/09/2026 e já implementada:

| Setor | Login(s) | Recursos TOTVS |
| --- | --- | --- |
| **Solda Aço** | `estacao1aco`..`estacao10aco` | os 41 códigos legados que já eram "Solda" |
| **Solda Alumínio** | `estacao1alu`..`estacao6alu` | nenhum ainda (nasce vazio, como Montagem) |
| **Solda Robô** | `robo1` (posto fixo) | `ROBO P`, `ROBO S` |
| **Proj. Ferramentaria** | `projetos` (pede seleção de recurso) | `DISPEX`, `DISPG`, `SERVGE`, `DISPOS` |
| **Protótipo** | `prototipo` (pede seleção de recurso) | `PREMTG`, `SOLDA4` |

Regras confirmadas: cada um é um `tipo_setor` real e distinto; todos seguem
elegibilidade aberta (qualquer recurso do setor é apontável, sem bloqueio de
recurso divergente — mesma exceção que já valia para "Solda" desde o commit
`44675f3`); no Andon os 5 aparecem como **sub-grupos dentro de 1 painel
"Solda"** (mesmo padrão do Corte para Laser/Plasma/Destaque), não como 5
painéis de topo; os 41 recursos legados de Solda Aço ficam no banco mas não
aparecem em telas/listagem por padrão (só "vêm para frente" se uma OP real
referenciar um deles no roteiro). Senha das contas novas é `1234`, só em
TEST — trocar manualmente antes do piloto em produção.

Commits relevantes: `fb2c707`, `44675f3`, `4ff7dce`, `9c39eb8`, `0dc50f9`,
`25f3208`, `da28772`, `382b1ee`, `17fbcba`, `d996e10`, `f37c3f8`.

Arquivos-chave: `app/core/operator_sectors.py`, `app/core/resource_mapping.py`
(`SECTOR_OWNED_RESOURCE_SECTORS`, `RESOURCE_CONFIRMATION_EXEMPT_SECTORS`),
`mes/services/andon.py`.

**Não reabrir esta investigação** sem fato novo — a especificação foi
aprovada sem ajuste pelo usuário.

### 1.2 Auditoria de segurança (14/09/2026) — 1 crítico corrigido; as 3 pendências foram resolvidas depois (ver nota ao fim da seção)

Relatório completo: `docs/AUDITORIA_SEGURANCA_2026-09-14.md`.

**Corrigido:**
- **Crítico**: o receptor SOAP do TOTVS (`POST /PcfIntegService`) não aceita
  mais uma origem não autorizada apenas por estar na LAN. Quando ativo, ele só
  atende IP/CIDR declarado em `GESTOR_TOTVS_SOAP_ALLOWED_SOURCE_CIDRS`; sem a
  configuração, o receptor fica indisponível (503), sem impedir a aplicação de
  iniciar. Hostname público continua bloqueado como segunda barreira.
- **Alto**: login do Dev Observatory sem freio de tentativa (credencial única
  guardando stack trace/leitura do REAL) — agora bloqueia por IP após 5
  falhas/300s. Corrigido de brinde um bug que derrubava o login com 500 em
  senha acentuada.

**Pendências que exigem decisão do usuário (não corrigidas de propósito):**
1. Login principal (`/api/v1/auth/login`) também sem freio de tentativa —
   não travado porque bloqueio total pode impedir operador de apontar no chão
   de fábrica. Sugestão do relatório: atraso progressivo por IP+usuário.
2. IDOR na Qualidade: `registrar_peca`/`finalizar_inspecao` não validam que o
   `inspecao_id` pertence ao setor do operador. Não corrigido porque
   `qualidade_inspecoes` não guarda o setor de origem — precisa migração de
   schema.
3. `.env` não define `GESTOR_WEB_SESSION_SECRET` nem
   `GESTOR_DEVOBS_SESSION_SECRET` — sessões caem a cada restart do processo.

**Situação conferida contra o código em 23/09/2026 — as três estão fechadas:**
1. Freio do login principal: atraso progressivo persistido por cliente+usuário
   em `login_throttle` (commit `779427f`, migration 48; F6).
2. IDOR da Qualidade: `QualityService._exigir_setor`
   (`mes/services/quality.py:110`) revalida o setor dono da inspeção em cada
   escrita e recusa com `qualidade_inspecao_outro_setor`; coberto em
   `tests/test_quality_inspection.py`.
3. Secrets de sessão: `GESTOR_WEB_SESSION_SECRET` e
   `GESTOR_DEVOBS_SESSION_SECRET` estão preenchidos no `.env` do TESTE; a
   revogação por versão de sessão veio em `f52c37c` (migration 47; F5).

Verificado como correto e não precisa mexer: SQL parametrizado, sem
subprocess/eval/pickle, XXE bloqueado, path traversal protegido, CSRF em
rotas de escrita, PBKDF2-SHA256 600k, sem `dangerouslySetInnerHTML`,
somente-leitura do REAL sem desvio. `pip-audit`: 0 vulnerabilidades.

### 1.3 Pente-fino de qualidade de código (14/09/2026)

Relatório completo: `docs/PENTE_FINO_2026-09-14.md`.

Corrigido: seed de homologação da Etapa 7A que estava quebrado desde a Wave 5
(faltava `autorizador_retrabalho`); uma query redundante em
`iniciar_intervalo_automatico`; 12 imports mortos; 27 arquivos-lixo (0 bytes
na raiz, um zip com `__pycache__` dentro, um `.pyc` órfão) movidos para
`_quarentena_revisar/` — **nada foi apagado**, é seguro revisar e apagar
depois.

**Pendência de negócio (não decidida):** roteiro de Pintura tem o mesmo posto
(`PINT.L`) aparecendo duas vezes (`PINT.L` op 40, `JATO` op 50, `PINT.L` op
60). O mapper projeta 3 operações separadas; 2 testes esperam dedupe. Decidir:
uma OP que repete o mesmo posto no roteiro vira duas operações apontáveis ou
uma só? (Hipótese do agente: duas, para não perder passo de pintura — mas é
decisão de chão de fábrica.)

Achado importante: a suíte de testes (899 testes) **não está inchada** — sem
duplicação real. A antiga falha conhecida em `manufacturing_rules.py`
(citada em relatórios anteriores a setembro) **não existe mais**.

Risco não resolvido: `docs/` está com ~120MB (evidências + screenshots).
Recomendado tirar da árvore principal, não executado ainda (mover em massa é
arriscado de desfazer).

### 1.4 Validação visual completa (14/09/2026)

Relatório completo: `docs/VALIDACAO_VISUAL_2026-09-14.md`. 55 telas/estados
cobertos. 8 defeitos corrigidos (fonte inconsistente em KPI, 4 casos de texto
cortado, Solda quebrada a 1024px, nome de operador com reticências
inconsistente, e um bug real: `MetricCard` mostrava número quando o indicador
vinha ausente do backend — caía silenciosamente no default `"disponivel"`).

**Decisão pendente (baixo risco):** o breakpoint de `.welding-macros__body`
foi movido de 900px para 1180px porque a 1024px a tabela da Solda comia o
espaço do gráfico de MACROs. Se 1024px não for largura real de uso no chão de
fábrica, é seguro reverter (`web/src/styles/welding.css`, uma linha).

Documentado sem alterar: densidade do Andon TV (18 textos <10px a 1920×1080)
— é consequência direta de "tudo cabe sem rolagem"; corrigir exigiria
redesenhar a tela, não é CSS.

### 1.5 Dev Observatory (13/09/2026) — implementado, testes agora passam

Observabilidade permanente só para o desenvolvedor (logs/erros/telas por
turno, TEST+REAL somente leitura). Vive em `backend/observability/` e
`backend/api/routers/dev_observatory.py`, rota `/api/v1/dev-observatory`.
Acesso ao REAL é somente-leitura garantido por prova de gravação recusada na
abertura da conexão (falha fechada). Relatórios automáticos por turno em
`dev_reports/<data>_<turno>/`.

A pendência antiga de `tests/test_dev_observatory` (7 testes com 404 por
fixture sem `dev_observatory_enabled=True`) **já está resolvida** — a flag já
está na fixture (`tests/test_dev_observatory.py:154`); 19/19 passando desde a
validação visual de 14/09.

### 1.6 Reunião de alinhamento do piloto TOTVS (14/09/2026)

Notas completas em memória do desenvolvedor; principais decisões fechadas:
- VM do piloto: Docker + Ubuntu Server 24.04 LTS, acesso só via API interna.
- Banco: mantém **PostgreSQL**, sem migração para MSSQL (decisão fechada —
  sistema já acoplado a Postgres, VM isolada não tem o problema que
  justificaria MSSQL, e MSSQL exigiria licença paga sem benefício técnico).
- OP fechada no TOTVS via finalização parcial do PCP (rejeição
  `A680OPTOT Operacao ja totalizada`): já não quebra nada tecnicamente
  (classificada `FUNCTIONAL` no outbox, sem retry infinito). A notificação ao
  supervisor foi ligada ao canal Alertas em 16/09/2026 (§2.9); permanece
  inativa enquanto o worker da outbox estiver desligado no ambiente.
- Cadastro de filial: piloto roda só na filial 4. Falta implementar: quando o
  TOTVS não mandar `branch_id`, usar `"4"` como padrão em vez de string vazia
  (`app/database/database.py:439`) — **implementado no commit `4a60564`**
  ("default de filial TOTVS"), conferir se cobre exatamente esse ponto antes
  de dar como fechado. **Atualização 23/09/2026:** o pull sob demanda passou a
  aceitar lista de filiais (`GESTOR_TOTVS_OP_PULL_BRANCH_ID` em CSV) e tenta
  cada uma em ordem, parando na primeira que encontra a OP ou no primeiro erro
  real de transporte (commit `5e91f56`, `mes/integrations/totvs/on_demand.py`).
- Retry/reconexão TOTVS: já resolvido antes desta reunião (outbox
  transacional + worker em background, backoff 1/2/5/10/30/60min).

**Pendência desta reunião encerrada em 16/09/2026:** rejeições `FUNCTIONAL`
usam o notifier existente e o destino transversal de Alertas (§2.9).

### 1.7 Commits mais recentes (não descritos em nenhum relatório datado)

```text
4a60564 feat: botão de chamada, cadastro de usuários e default de filial TOTVS
f37c3f8 fix: Projetos e Protótipo passam a pedir seleção de recurso
d996e10 fix: rótulo de SOLDA4 deixa de dizer "Solda" (agora é do Protótipo)
```

O commit `4a60564` trouxe: sistema de "chamada" (botão + sino) para o
operador acionar alguém — `web/src/components/ChamadaButton.tsx`,
`ChamadaSino.tsx`, `app/database/chamada_repository.py`,
`backend/api/routers/chamadas.py`; cadastro de usuários gerenciais
(`web/src/pages/home/UsersPage.tsx`, testado em
`tests/test_user_management.py`); integração de notificações
(`mes/integrations/notifications/telegram.py` — base efetivamente reutilizada
para a notificação `FUNCTIONAL` fechada na §2.9); e o
default de filial TOTVS mencionado acima.

## 2. Working tree com alterações não commitadas (verificar antes de mexer)

> **Obsoleto em 23/09/2026:** o trabalho descrito abaixo já foi commitado e
> o working tree está limpo (conferido com `git status` no fechamento da
> auditoria F1–F21). O parágrafo fica só como histórico.

Em 15/09/2026 o `git status` mostra trabalho em andamento, aparentemente uma
reorganização da navegação em abas ("painéis") agrupando Chamadas/Crachás
(Badges)/Metas/Pausas/Usuários sob uma barra nova:

- novo componente `web/src/components/PanelsTabBar.tsx`;
- novos ícones `assets/web/navigation/dev.svg` e `panels.svg`;
- `web/src/config/navigation.ts`, `web/src/layouts/AppShell.tsx` e as páginas
  de `web/src/pages/home/*` alteradas para usar essa nova barra;
- testes `web/src/test/andon.test.tsx` e `management.test.tsx` ajustados;
- `backend/api/routers/management.py` e `tests/test_user_management.py` com
  pequenos ajustes.
- Dois arquivos de 0 bytes (`0`, `None` — lixo do tipo já descrito no
  pente-fino) estão marcados para exclusão (`D`), coerente com a limpeza.

**Este é trabalho em progresso de uma sessão anterior — não descartar, não
commitar sem entender, e não recriar do zero.** Rodar `git diff` para ver o
estado exato antes de continuar essa frente.

### 2.1 Correção visual do Andon/Painéis Operacionais (15/09/2026)

O botão de navegação do Andon/Solda estava `position: fixed`, por isso ficava
sobre o primeiro card de Corte; a troca pela navegação lateral também havia
removido as sub-abas de Painéis Operacionais dessas páginas cheias. A faixa
`AndonSidebarNav` agora participa do fluxo normal, acima do quadro, mantém as
abas Andon, Solda, Metas e Pausas e permite recolhê-las sem voltar a sobrepor
cards. A tela/rota de Chamadas foi movida para o IagoDev, sem mudar seus
contratos ou autorização. Cobertura direcionada em `web/src/test/andon.test.tsx`
valida a faixa, as abas e o ciclo minimizar/restaurar.

Os itens de priorização da Visão Geral também passaram a ser acionáveis
(15/09/2026): exceções de parada, perdas por motivo e recursos críticos levam
à análise de Paradas; uma exceção de tempo padrão leva à análise Tempo Padrão ×
Real; e uma exceção de meta leva ao painel de Metas. O período já selecionado é
preservado, e recurso/setor/OP/operação são reaplicados quando a análise aceita
esses filtros. Nenhum contrato do backend foi alterado.

Todos os cards grandes da Visão Geral também são clicáveis sem aninhar links
ou botões: Planejado × Realizado abre Produção, Composição do tempo abre Tempo
MES, Setores abre Recursos e Inconsistências abre a Auditoria. O controle de
navegação é acessível por teclado e os botões internos dos cards mantêm seus
atalhos específicos.

**Correção Full HD (15/09/2026):** no Andon gerencial, a faixa de navegação
passou a ocupar uma linha `auto` própria no grid em 1920×1080; antes ela tomava
a única linha flexível e empurrava o quadro para baixo, deixando um grande vazio
acima das abas. O menu e as sub-abas continuam no fluxo normal, sem sobrepor os
cartões.

### 2.2 Diagnóstico da chamada por Telegram (15/09/2026)

O fluxo do botão foi conferido de ponta a ponta: a chamada é persistida antes
do envio, o contato selecionado define o destino e a falha do Telegram fica
registrada sem desfazer a chamada. No banco `gestor_pecas_test`, o destino
pessoal informado pelo usuário foi associado ao contato Iago; o identificador
não foi versionado nem copiado para este documento.

O token do bot foi configurado somente no `.env` local e a integração foi
habilitada, sem copiar a credencial para código ou documentação. Após a
normalização da conectividade externa, um envio real controlado foi confirmado
para o contato Iago no ambiente TESTE. O botão de Chamada já usa esse mesmo
destino, token e transporte; a credencial continua fora do repositório.

### 2.3 Identificação de chamada por crachá (15/09/2026)

No botão de chamada do operador, o crachá continua obrigatório, mas deixou de
ser tratado como nome. Antes de persistir a chamada ou montar o aviso do
Telegram, a API resolve o crachá no cadastro ativo canônico de operadores. Um
crachá inexistente/inativo é recusado e não cria chamada; o histórico e a
mensagem passam a mostrar o nome cadastrado, mantendo o crachá como
identificação complementar.

### 2.3 Retomada automática de pausas e abertura do turno (15/09/2026)

Regra confirmada com o usuário: toda parada automática cadastrada em
`pausas_automaticas_setor` termina sozinha no `hora_fim` configurado (almoço,
café ou outra pausa), retomando o estado físico que ainda estiver sustentado
pela execução. Se o operador tiver declarado outro estado durante a pausa, o
scheduler não o sobrescreve.

A causa da falha era de execução: `ShiftBoundaryService` já calculava os dois
limites e o repositório já sabia finalizar a pausa, mas o ciclo em
`backend/api/main.py` só era criado com a simulação acelerada. O ciclo agora
fica ativo também no relógio normal; mesmo quando detecta alguns segundos
depois, persiste a transição exatamente no horário configurado.

Na abertura do turno oficial às **08:00**, um `fora_turno` automático ainda
aberto é encerrado e passa para a leitura **Recurso sem demanda**. A OP
interrompida continua em `Parada` e exige retomada manual: o retorno do
calendário não presume OP, produção nem outro estado físico. A persistência usa
`fila` com origem/tipo `retorno_turno_sem_demanda`, sem vínculo de OP; a fachada
remove a OP parada somente dessa projeção lógica. Uma fila operacional comum
dentro do turno continua não significando "sem demanda".

### 2.4 Limpeza controlada de OPs do TESTE (16/09/2026)

O banco `gestor_pecas_test` foi limpo pela rotina transacional
`scripts/resetar_banco_teste.py`, após simulação e confirmação literal do alvo.
Foram removidos 71.336 registros de planejamento de OP, execução, Corte,
Qualidade, outbox e envelopes `ProductionOrder`; usuários, recursos,
calendários, configurações, mensagens de integração não-OP e schema 37 foram
preservados. O banco `gestor_pecas` foi verificado exclusivamente em modo
somente leitura.

### 2.5 Consulta Operacional: recursos sem demanda por conta ativa (16/09/2026)

`Sem demanda` e `Fora de turno` aparecem em **Consulta Operacional → Visão
geral/Recursos**, somente para recursos configurados nos perfis de contas
operacionais ativas em `usuarios`. A projeção não consulta o inventário
inteiro, nem deduz recurso por OP, rota ou demanda; contas inativas e perfis
sem recurso não geram linha. No TESTE limpo, a conferência real exibiu 34
recursos. Na Visão Geral, os cartões são exibidos por setor selecionável e
usam o nome descritivo oficial do cadastro (por exemplo, `DISPEX` aparece como
`DISPOSITIVO EXPORTAÇÃO`); o código técnico permanece apenas como identidade
interna. O Andon e o Dev Observatory permanecem restritos a
apontamentos compatíveis/canônicos, sem misturar disponibilidade cadastrada à
evidência de execução.

### 2.6 Corte libera a OP independentemente do Destaque (16/09/2026)

Quando todos os nestings ativos que contêm uma OP são finalizados no Corte, a
etapa oficial `CORTE` dessa OP passa a ser considerada concluída e libera a
próxima etapa do roteiro. A associação é por OP + programa/nesting; outra OP do
mesmo agrupamento não bloqueia seu avanço. O Destaque continua sendo uma fila
operacional independente para contabilizar tempo e não é pré-requisito para o
avanço do roteiro, mesmo enquanto ainda não possui recurso oficial cadastrado.

### 2.7 Bot de fábrica no Telegram ativado no TESTE (16/09/2026)

O `.env` local do TESTE foi configurado com polling privado e resumos automáticos
ativos para o grupo `-1003542149782`. O backend da porta 8001 foi reiniciado com
alvo efetivo comprovado em `gestor_pecas_test` (schema 39); a identidade remota
confirmada é `@Gestordepecas_bot`. Como o restart ocorreu antes das 18:00 BRT,
o ciclo de digest não enviou resumo na inicialização (`telegram_digest_envios`
permaneceu vazio). Os comandos privados aguardam a validação humana de
`/vincular <cracha>` seguida de `/meustatus` com um crachá real.

### 2.8 Registro de chats Telegram descobertos (16/09/2026)

O polling do bot registra de forma idempotente cada `group`, `supergroup` ou
`channel` que enviar uma atualização, em `telegram_chats_descobertos` (migration
40), guardando `chat_id`, tipo e título. O registro não responde nesses chats,
não habilita comandos fora do privado e não os transforma em destinos de digest.
Para consultar, usar `Database.listar_chats_telegram_descobertos()` ou uma query
somente leitura na tabela; publicar uma mensagem/postagem nova depois da
atualização do backend para o chat ser descoberto.

### 2.9 Roteamento Telegram por frente industrial (16/09/2026)

O digest automático passou a ter cinco destinos sem sobreposição: **Alertas**
recebe somente o consolidado global; Corte, Solda, Pintura e Caldeiraria recebem
somente a sua frente. Os escopos são derivados do agrupamento canônico do Andon:
Caldeiraria = Dobra/Usinagem/Serra e Solda = os cinco setores oficiais de
`WELDING_SECTOR_NAMES`. Nenhuma equivalência por texto foi criada. A configuração
local usa `GESTOR_TELEGRAM_SECTOR_CHAT_IDS`; o controle existente em
`telegram_digest_envios` ganhou chave lógica por frequência + escopo, preservando
a chave global legada e evitando reenvio pelo scheduler sem migration nova.

As mensagens foram reduzidas a quatro ou cinco linhas. O consolidado e os painéis
de um setor continuam usando os KPIs canônicos; frentes compostas somam somente
grandezas aditivas (quantidades e tempos) e não inventam um OEE agregado. A rejeição
`FUNCTIONAL` do outbox já usa `build_outbox_error_notifier` e agora aponta para
Alertas (`-1003542149782`). O outbound e seu worker permanecem desligados no
`.env`, conforme a decisão anterior; portanto esse aviso só roda quando o piloto
TOTVS for explicitamente reativado.

Validação dirigida: **26 testes aprovados** (`tests.test_telegram_bot` e
`tests.test_totvs_outbox_notifications`), `py_compile`, `git diff --check`,
preview somente leitura dos cinco textos e alvo literal
`current_database() = gestor_pecas_test`, schema 40. O backend 8001 foi reiniciado
e respondeu `health=ok`. A Bot API confirmou `@Gestordepecas_bot` como
administrador nos cinco destinos. Depois dessas validações foram enviados
exatamente **15 cenários marcados TESTE/HOMOLOGAÇÃO** (acompanhamento, alerta
acionável e desfecho; três por destino), com OP/produto/operador de referências
existentes no banco TESTE, sem persistir evento produtivo. Resultado externo:
**15/15 ACKs `ok=true`**.

### 2.10 Interface Telegram privada e padrão visual (17/09/2026)

O bot privado ganhou `/start` e `/menu`, menu inline estável, navegação por
callbacks diretos (`gp:*`) com edição da mensagem atual, resposta obrigatória ao
callback e fallback de envio quando a edição não é possível. Os comandos
existentes e o parser determinístico de linguagem natural convergem nas mesmas
consultas somente-leitura da `FrontendBackendFacade`; nenhuma regra de produção,
parada ou OEE foi levada para o Telegram. Corte, Solda, Pintura e Caldeiraria
continuam derivados do agrupamento canônico do Andon.

A apresentação HTML ficou centralizada em `mes/services/telegram_presenter.py`,
com escape dos dados dinâmicos, rodapés sem segundos, números pt-BR, estados sem
dado e teclados com estilo semântico da Bot API. O transporte agora valida ACK
para `sendMessage`, `editMessageText` e `answerCallbackQuery`; uma edição sem
alteração é tratada como sucesso para não gerar mensagem duplicada. Grupos e
canais continuam apenas com descoberta silenciosa e notificações automáticas.

Os digests usam a mesma identidade visual. O destino global local foi movido do
chat de Alertas para o canal descoberto **🏭 | Fábrica** pela configuração
`GESTOR_TELEGRAM_FACTORY_CHAT_ID`; o alerta da outbox TOTVS permanece no chat
separado de Alertas e diferencia rejeição funcional de falha técnica, lendo os
campos reais persistidos (`last_delivery_class`, `last_error_message` e
`payload_context`). A lógica e os estados da outbox não mudaram.

Validação dirigida: `current_database() = gestor_pecas_test`, **37 testes
aprovados** (`tests.test_telegram_bot` e
`tests.test_totvs_outbox_notifications`), `py_compile` e `git diff --check`.
Não houve migration nem envio externo nesta alteração. Após o commit, somente o
backend 8001 foi reiniciado: `health=ok`, schema 40, banco efetivo
`gestor_pecas_test`, polling e digest ativos, destino global Fábrica e quatro
destinos setoriais carregados, sem erro no log de startup.

### 2.11 Atualização de planos de Corte no Telegram (17/09/2026)

O apontamento canônico de Corte passou a publicar no destino setorial de Corte
uma mensagem compacta com `Tarefa`, `Plano` e, quando há repetição do mesmo
plano, `Nesting`. O primeiro apontamento usa `sendMessage`; os apontamentos
seguintes editam a mesma mensagem com `editMessageText`, mantendo correlação
idempotente por chat, tarefa e recurso. Se a edição não for possível, o fluxo
envia uma nova mensagem e atualiza a correlação. A falha do Telegram é isolada
do apontamento industrial já persistido.

Foi acrescentada a migration 41 (`telegram_corte_mensagens`) e o transporte
passou a expor o `message_id` confirmado pelo ACK do Telegram. A apresentação
escapa HTML e mantém o rodapé de evento sem segundos. Testes dirigidos do
notificador e da interface Telegram passaram. A migration foi aplicada no
TESTE (`gestor_pecas_test`, schema 41) e o backend 8001 foi reiniciado com
health `ok`, mantendo polling/digest e os destinos setoriais configurados.

### 2.12 Contexto condicional de setor e operador no Telegram (17/09/2026)

Mensagens com OP passaram a incluir `Setor` somente quando o apontamento
fornece esse campo. O contexto de `Operador` continua condicional: quando não
há operador real no apontamento, a coluna é omitida em vez de exibir um
placeholder como "Não encontrado". Eventos de Corte exibem o setor canônico
`Corte` e também omitem operador quando a execução não o informa.

### 2.13 Filtros gerenciais coerentes com cada fonte (17/09/2026)

A barra de filtros passou a declarar os campos que cada consulta realmente
aceita. Na rastreabilidade de nestings, somente período e recurso são enviados:
os demais filtros antes faziam o serviço retornar lista vazia. O período rápido
aplica imediatamente o rascunho atual, filtros avançados ativos ficam visíveis
e a interface não oferece mais o filtro de turno, que não era consumido pelas
fontes gerenciais. Validação dirigida: filtros de simulação **6/6** e build
Web (`tsc -b` + Vite) concluídos. O teste gerencial amplo continua com duas
falhas pré-existentes, fora desta alteração: contagem fixa de rotas e expectativa
do rótulo legado `DOBRA1`.

### 2.14 Primeira onda de refatoração estrutural (17/09/2026)

A auditoria estrutural removeu módulos, arquivos vazios, caches TypeScript,
dependência Web e contratos sem consumidor comprovado; consolidou a
serialização dos contratos gerenciais, eliminou o ciclo entre a página-raiz do
operador e suas páginas filhas, e tornou o manifesto de tabelas a fonte única
para diagnóstico e reset do TESTE. Nenhuma regra industrial, endpoint, schema
histórico ou banco REAL foi alterado. O relatório, as métricas de partida e as
próximas ondas estão em `docs/REFACTORACAO_ESTRUTURAL_2026-09-17.md`.

### 2.15 Correções de tempo, Corte, Destaque e ausência de demanda (21/09/2026)

- Capacidade planejada deixou de usar o segundo corrente como fim do período;
  a soma da fábrica não transforma mais segundos reais em vários minutos.
- A tela de Corte chama de plano a unidade sem repetição (`Plano 1/18` e
  `Finalizar plano`) e reserva nesting para repetição real da chapa no plano.
- A fila do Destaque foi confirmada no TESTE para a tarefa `T3609`: planos do
  Laser Ensis entram e Plasma continua excluído. A tela agora lista primeiro
  somente planos já cortados, aponta início/parada/retomada/fim por plano e
  consome o read model canônico devolvido pela mutação para atualizar os botões.
- Toda fila física sem OP é projetada centralmente como `Recurso sem demanda`;
  fila vinculada a OP não é reclassificada. A categoria `Fila / espera` saiu
  das composições, insights e planilhas gerenciais.

### 2.16 Atividade sem OP e consulta de recursos no Telegram (21/09/2026)

- O posto pode iniciar e finalizar **Atividade sem OP** como estado físico
  produtivo do recurso, sem apontamento, quantidade ou crachá. Corte e Destaque
  classificam-na como `Atividade diária`; os outros setores usam o rótulo geral.
  O tipo é decidido pelo setor e persistido no estado canônico (schema 42), não
  pela interface. Corte e Destaque expõem o mesmo fluxo sem criar uma segunda
  regra para tarefa/plano.
- O bot privado ganhou `/recursos <frente>` e o botão equivalente: mostra o
  estado e o contexto operacional dos recursos da frente pelo snapshot canônico,
  sem comando produtivo. A classificação de falhas HTTP do TOTVS também foi
  consolidada em um único módulo compartilhado pelos três gateways.

### 2.17 Estados de recurso e reset localizado de OPs (21/09/2026)

- A leitura do estado atual carrega novamente a taxonomia do motivo do catálogo.
  Assim, a pausa `0009 — PAUSA PARA CAFÉ` (grupo `0002 — PARADA PROGRAMADA`)
  permanece planejada mesmo quando lançada manualmente; não reduz OEE.
- A projeção do Andon consolida o código técnico e o nome do posto como uma só
  máquina (`LASER1`/`Laser Ensis 3015`), e recursos sem OP são classificados
  centralmente como `Recurso sem demanda`, nunca como uma fila operacional.
- No TESTE, `PCMITL01001` e `PCMIDN01017` voltaram ao ponto inicial de Dobra:
  execução, quantidade, primeira peça, alertas e histórico foram removidos em
  transação estreita. Catálogo, sincronização inbound e os 16 apontamentos de
  Corte finalizados vinculados às duas OPs foram preservados; `CORTE` continua
  concluído e Dobra volta a ser a próxima etapa elegível.
- Setup passou a exigir o `Início` prévio da mesma OP. O bloqueio é canônico
  (`setup_exige_inicio`, HTTP 409), e o botão do posto permanece desabilitado
  enquanto não houver apontamento ativo; não é apenas uma restrição visual.

### 2.18 Hooks locais do Codex alinhados ao Claude (22/09/2026)

O `.codex/hooks.json` local preserva os guards Graphify, o type-check de
TypeScript e os hooks globais do Brain. Foi alinhado aos hooks recentes do
Claude com o lembrete Ponytail em cada prompt, a compressão Headroom para
saídas grandes de Bash/Grep (limite de 12.000 bytes) e o autostart do proxy
Headroom na abertura da sessão. Os comandos usam o Git Bash local de forma
explícita, pois `bash` não está no `PATH` do PowerShell. O OmniRoute deixou de
ser iniciado automaticamente pelo Codex; permanece opcional e configurável
separadamente.

Validação dirigida: JSON do hook, sintaxe dos scripts Bash, saída do lembrete,
limiar Headroom e resolução do runtime Git Bash.

### 2.19 Matriz operacional Claude → Codex (22/09/2026)

A auditoria de instruções, memória, skills, hooks, agentes, comandos, MCPs,
plugins, permissões e Git está consolidada em `docs/CODEX_PARIDADE_CLAUDE.md`.
O inventário completo tem 900 arquivos `SKILL.md`: 68 skills individuais e 832
automações Composio. As individuais permanecem nativas/compartilhadas no Codex,
e as 832 Composio foram espelhadas, arquivo a arquivo, no catálogo sob demanda
do Codex; 29 duplicatas idênticas da biblioteca compartilhada foram arquivadas,
mantendo as cópias nativas. O resultado preserva a descoberta sem perda integral
das descrições. O limite nativo de instruções foi ajustado para 96 KB, carregando
integralmente o `AGENTS.md` de 72,5 KB. O novo hook ainda exige confiança
explícita do Codex na próxima sessão. O launcher Headroom órfão foi restaurado
offline da versão cacheada 0.37.0 (com extra MCP) e validou `initialize` e o
pipeline `headroom_compress`.
O pg_aiguide também respondeu a `initialize`, `tools/list` e `search_docs`
somente-leitura; a pendência MCP fica restrita ao OmniRoute.

### 2.20 Skill e detector visual Impeccable no Codex (22/09/2026)

A skill local `impeccable` (v4.3.1) foi vinculada ao catálogo global do Codex,
reaproveitando a fonte única em `.claude/skills/impeccable`. O detector visual
foi habilitado por projeto: roda a verificação imediata depois de `Write/Edit`
e a análise profunda no encerramento da sessão, sem substituir Graphify,
type-check, Headroom, Ponytail ou Brain. As configurações geradas em
`.impeccable/` permanecem locais e ainda não foram versionadas.

Validação dirigida: manifesto JSON, ambos os comandos do detector com entrada
de evento não visual, status `enabled` sem exceções configuradas e vínculo da
skill global ao diretório do projeto.

### 2.21 Deploy preserva dados de runtime (23/09/2026)

O espelho de deploy da VM preserva explicitamente `.env`, `dados/`,
`dev_reports/` e `backups/`; estes diretórios não participam mais do `robocopy
/MIR`. O health check após reinício passou a ter timeout total de 60 segundos,
tentativas de 3 segundos e timeout por requisição. O ensaio
`scripts/test_deploy_mirror.ps1` usa somente diretório temporário e comprovou
que código obsoleto é removido, enquanto dados de runtime permanecem após dois
espelhamentos consecutivos. Commit: `7727432`.

### 2.22 Refugo da primeira peça é canônico e atômico (23/09/2026)

O descarte da primeira peça deixou de atualizar apenas o saldo do apontamento.
Na mesma transação ele agora grava o estado `primeira_peca_refugo`, o evento
canônico de quantidade e a obrigação da outbox TOTVS quando ela estiver
habilitada. A migration 44 registra o novo estado permitido. Se não existir
apontamento operacional, o refugo é recusado sem gravar uma decisão parcial.

Em OP unitária, refugo esgota o saldo planejado; uma nova peça conforme serve
para liberar o portão de qualidade e a finalização sem nova quantidade passa a
fechar a operação. A prova dirigida cobre o fluxo em memória, o PostgreSQL em
schema descartável e o planejamento da outbox.

### 2.23 Perfis desconhecidos falham fechados (23/09/2026)

Somente o nível legado explícito `comum` continua compatível com
`operador_destaque`. Qualquer outro perfil fora do catálogo não recebe mais
essa permissão por fallback: login e revalidação da sessão retornam 403, e as
funções de navegação/permissão não concedem acesso. A cobertura HTTP inclui uma
conta persistida com nível inválido.

### 2.24 Catálogo de migrations é validado antes do banco (23/09/2026)

O migrador verifica que toda versão até `SCHEMA_VERSION` existe no catálogo
antes de abrir a transação. Uma versão declarada sem migration agora produz
erro de configuração explícito, em vez de um `KeyError` tardio após iniciar a
atualização do schema.

### 2.25 Banco de teste exige identidade literal (23/09/2026)

`TEST_DATABASE_URL` não é mais aceito apenas porque o nome contém `test`.
Ele exige `GESTOR_EXPECTED_DATABASE` e compara o alvo literalmente, mantendo
também a recusa quando o DSN coincide com o banco operacional.

### 2.26 Cursor do Telegram sobrevive a reinícios (23/09/2026)

O long polling do bot persiste o próximo `update_id` em
`telegram_bot_cursors` (migration 45) após cada atualização processada. Assim,
um reinício consulta a partir do cursor confirmado em vez de voltar ao início
da fila do Telegram.

### 2.27 Andon preserva recursos ativos sem painel prévio (23/09/2026)

Montagem passou a ter painel próprio quando houver recurso ativo e um recurso
com setor ainda não classificado aparece em `Não classificado`, mantendo o
nome recebido como grupo auditável. Nenhum recurso é promovido por semelhança
de texto. A página Web respeita a ordem e os painéis retornados pelo backend,
em vez de manter uma segunda lista de setores; painéis extras usam o ícone
oficial genérico de painéis.

Validação dirigida: `tests.test_andon_redesign` (16 testes),
`web/src/test/andon.test.tsx` (15 testes), `npm run build` e detector
Impeccable sem achados.

### 2.28 Teto de produção acompanha o planejamento PCP (23/09/2026)

O Início não transforma mais quantidade ausente em teto de uma peça: a OP é
recusada com estado operacional explicado. A quantidade persistida em um
apontamento ainda ativo acompanha a revisão do catálogo PCP; apontamento já
finalizado não é reescrito. Se o PCP reduzir a quantidade abaixo do que já foi
atendido, o teto efetivo preserva o atendido e impede produção adicional, sem
forjar uma violação histórica.

Validação dirigida: `tests.test_operator_flow` e dois testes PostgreSQL de
`test_database_professionalization` (32 testes no total) passaram.

### 2.29 Dev Observatory exige CSRF próprio (23/09/2026)

O POST de geração de relatórios do Dev Observatory agora exige o token CSRF
emitido junto com a sessão exclusiva da ferramenta. O guard não reutiliza o
cookie da sessão principal; compara o header e o cookie legível com o token
assinado da sessão do observatório. Logout remove os dois cookies. O relatório
continua sendo uma projeção somente leitura, sem escrita de dados operacionais.

Validação dirigida: `tests.test_dev_observatory` (20 testes) passou, incluindo
a recusa explícita de POST sem CSRF.

### 2.30 Identidade de operador é preservada por ID (23/09/2026)

O apontamento operacional agora registra o ID imutável do primeiro crachá
informado no Início e no Fim. Participações passam a usar a identidade como
chave de exclusividade e retornam crachá/nome resolvidos do cadastro atual.
Snapshots de texto continuam apenas como compatibilidade para fatos legados ou
ações sem crachá; nenhum nome antigo é associado por inferência.

Validação dirigida: `tests.test_database_professionalization` e
`tests.test_wave5_1` (87 testes) passaram. A cobertura PostgreSQL renomeia um
crachá após o apontamento e confirma que apontamento, eventos e tempo-pessoa
permanecem no mesmo ID, com o novo nome exibido na leitura. A regressão de
consistência execução→gestão (11 testes) também passou com a identidade canônica
do recurso.

### 2.31 Receptor SOAP TOTVS falha fechado por origem (23/09/2026)

O receptor inbound não usa mais `Host` ou `X-Forwarded-For` para provar quem
envia a OP. `GET /PcfIntegService?wsdl` e `POST /PcfIntegService` verificam o
peer TCP contra `GESTOR_TOTVS_SOAP_ALLOWED_SOURCE_CIDRS`; CIDR inválido é erro
de configuração e allowlist ausente fecha apenas o receptor com 503, antes da
leitura do envelope. Para o TESTE, falta registrar o IP/CIDR real do servidor
Protheus nessa variável — não há chamada externa nem valor inventado aqui.

Validação dirigida: `tests.test_totvs_integration` (39 testes) passou, incluindo
origem permitida, origem negada mesmo com `X-Forwarded-For` forjado e allowlist
ausente.

### 2.32 Dev Observatory exige credencial sem escrita (23/09/2026)

Além da sessão PostgreSQL somente leitura e da prova de `CREATE TEMP TABLE`
recusada, a abertura agora consulta os privilégios efetivos da credencial. Papel
elevado, `CREATE` em banco/schema ou escrita em tabela/sequência fazem a
observação falhar fechada. A credencial atual do banco TESTE, que é gravável,
foi recusada pela própria verificação; uma role exclusiva com `SELECT` continua
sendo necessária para habilitar a observação do REAL.

Validação dirigida: `tests.test_dev_observatory` (20 testes), compilação e
prova no PostgreSQL TESTE passaram.

### 2.33 Backup local restaurável do TESTE (23/09/2026)

`scripts/backup_banco_teste.py` só aceita `gestor_pecas_test` após confirmação
literal. Ele executa `pg_dump` em formato custom dentro do serviço Docker,
valida o archive com `pg_restore --list` sem restaurar dados e produz manifesto
SHA-256. Um dump efetivo de 5.093.524 bytes foi criado e validado em
`backups/test/`, diretório local ignorado pelo Git. O procedimento está em
`docs/BACKUP_TESTE.md`.

Validação dirigida: `tests.test_backup_banco_teste` e
`tests.test_resetar_banco_teste` (10 testes) passaram, além do dry-run e do
backup TESTE efetivo.

Complemento (commit `1c4842c`): `--verificar` confere manifesto, tamanho,
SHA-256 e `pg_restore --list`; `--restaurar` só aceita banco descartável
`gestor_restore_*` vazio e confirmado literalmente, e restaura em transação
única; log JSON em stderr e códigos de saída 0/1/2/3. Ensaio real em
23/09/2026: backup de 5.102.867 bytes verificado e restaurado em
`gestor_restore_20260923` (253 tabelas na origem e no restaurado), alvo
`gestor_pecas` recusado com exit 2, reexecução sobre o alvo já preenchido
recusada com exit 2, banco de ensaio removido em seguida. Runbook para a
infra em `docs/BACKUP_TESTE.md`.

### 2.34 Instância `:8001` reiniciada com o código atual (23/09/2026)

O processo TESTE em `:8001` estava rodando código anterior às correções de
segurança (WSDL respondia `200` sem allowlist configurada). Reiniciado com o
mesmo comando (`uvicorn backend.api.main:app --host 127.0.0.1 --port 8001`,
config via `.env`). Confirmado após reinício: `GET /health` → `200`;
`GET /PcfIntegService` → `503 totvs_soap_source_not_configured` (fail-closed
correto, nenhum CIDR foi configurado). Nenhuma credencial de escrita foi
apontada para o Dev Observatory nesta janela.

### 2.35 Role somente-leitura do Dev Observatory provisionada (23/09/2026)

Usuário autorizou explicitamente mexer no banco REAL nesta janela (sistema
ainda não roda na fábrica). Criada a role `gestor_devobs` em `gestor_pecas`
via `CREATE ROLE ... NOSUPERUSER NOCREATEDB` + `GRANT SELECT` em todas as
tabelas do schema `public` + `ALTER DEFAULT PRIVILEGES` + `default_transaction_read_only=on`,
exatamente como documentado em `backend/observability/readonly_db.py`.
`GESTOR_DEVOBS_REAL_DATABASE_URL` preenchida no `.env` real. Verificado
manualmente contra o servidor, replicando a prova do próprio código
(`verify_read_only`): `elevated_role=False`, `database_create=False`,
`CREATE TEMP TABLE` recusado em transação read-only, `SELECT` funcionando
normalmente. Backend `:8001` reiniciado para carregar a nova variável.
Gate F4/F9 fica reduzido a apenas o CIDR do SOAP (item 8 abaixo).

### 2.36 F18 — GPOPSYNC não resolve, mas abre um caminho empírico (23/09/2026)

`fontes/10-PCP/GPOPSYNC.prw` (canal de pull homologado, hoje o mecanismo
principal de sincronização — ver nota abaixo) reaproveita a mesma cadeia
oficial (`MATA650PPI → PCPa650PPI → MATI650`) que já alimenta o receptor
SOAP passivo. Não monta `StatusOrderType` por conta própria, então puxar uma
OP qualquer por ele devolveria o mesmo valor `"1"` já observado — não é uma
segunda fonte de dado. O que ele permite, e que a doc oficial não: puxar sob
demanda uma OP que o usuário confirme estar **cancelada/excluída no
Protheus** e inspecionar o `StatusOrderType` real devolvido. Isso resolveria
F18 com evidência empírica, sem depender de contrato TOTVS — mas exige o
usuário indicar uma OP real nessa condição; não implementado nesta janela.

**Reclassificado em 23/09/2026 — F18 = RECLASSIFICADO / NÃO ERA BUG.** A regra
de negócio foi confirmada pelo usuário: não existe estado operacional
"cancelado"; Protheus é planejamento e o MES é execução; a execução já
registrada no MES nunca é apagada, invalidada ou interrompida retroativamente
quando o Protheus encerra ou exclui a OP; uma recusa funcional no outbound vira
notificação ao supervisor, preservando o fato do MES. Portanto não há
`StatusOrderType` terminal a interpretar e o caminho empírico acima deixa de
ser necessário. O código já cumpre a regra:

- `mes/integrations/totvs/on_demand.py:244-246` — OP existente localmente
  retorna antes de qualquer chamada ao ERP; um 404 do Protheus nunca alcança
  uma OP local.
- `mes/integrations/totvs/on_demand.py:338-351` — `not_found` só encerra a
  solicitação de sync como `NOT_FOUND`; não cria nem desativa nada.
- `mes/integrations/totvs/outbox.py:187-196` — rejeição de negócio
  (ex.: `A680OPTOT`) vira `FUNCTIONAL`/`ERROR` sem retry.
- `app/database/totvs_outbox_repository.py:289` (`concluir_item_outbound_totvs`)
  — grava só `totvs_outbox`/`totvs_outbox_attempts`; nenhum apontamento é
  tocado.
- `mes/services/totvs_outbox_worker.py:224-226` — item em `ERROR` aciona
  `_notify_error` (canal Alertas, §2.9).

Testes que fixam a regra (commit `b51cc06`):
`tests/test_totvs_outbox.py::test_rejeicao_funcional_preserva_o_fato_do_mes`
(fotografa as tabelas do MES antes/depois de uma rejeição funcional) e
`tests/test_totvs_on_demand.py::test_op_local_nao_e_desativada_mesmo_que_o_erp_responda_404`.
Não implementar exclusão/cancelamento por inferência nem desativar OP por 404.

Nota sobre prioridade: o receptor SOAP `PcfIntegService` foi a *primeira*
forma de sincronização (documentada em
`docs/INTEGRACAO_TOTVS_PRODUCTION_ORDER_V1.md`), mas hoje o canal
efetivamente em uso é o pull via `GPOPSYNC` (Etapa 7B, homologado
03/09/2026). O gate do CIDR do SOAP (item 8) portanto trava um canal legado
que segue existindo no código por segurança, não o caminho operacional atual.

### 2.37 Fechamento da auditoria F1–F21 (23/09/2026)

Cada item tem um único status. Hashes são os commits de correção/prova.

| Item | Status | Evidência |
| --- | --- | --- |
| F1 SCHEMA_VERSION | CORRIGIDO E PROVADO | `cd19478`; código e TESTE em 49 |
| F2 normalização de papéis | CORRIGIDO E PROVADO | `6d3eeac` (§2.23) |
| F3 caminho do banco de produção | CORRIGIDO E PROVADO | `506a92f` (§2.25) |
| F4 autenticação do receptor SOAP | CORRIGIDO E PROVADO | `8f0aa6c` (§2.31); ativação depende do CIDR do Protheus (item 8 da §3) |
| F5 revogação de sessão | CORRIGIDO E PROVADO | `f52c37c`, migration 47 |
| F6 throttle do login | CORRIGIDO E PROVADO | `779427f`, migration 48 |
| F7 identidade do operador | CORRIGIDO E PROVADO | `b3b0fb8` (§2.30) |
| F8 cursor do Telegram | CORRIGIDO E PROVADO | `d429d9d`, `455de35`, `56d7102`, `212f114`, migration 45 |
| F9 papel/CSRF do Dev Observatory | CORRIGIDO E PROVADO | `76117cb`, `8f0aa6c`, role `gestor_devobs` (§2.35) |
| F10 OP unitária com 1ª peça refugada | CORRIGIDO E PROVADO | `fb85084`, migration 44 |
| F11 refugo canônico da 1ª peça | CORRIGIDO E PROVADO | `fb85084` (§2.22) |
| F12 exclusividade de recurso | CORRIGIDO E PROVADO | `3ec7ddf` |
| F13 escritores do calendário | CORRIGIDO E PROVADO | `34fc44b` |
| F14 crachá de exceção | CORRIGIDO E PROVADO | `7dfbf07` |
| F15 `parametros_turno` | CORRIGIDO E PROVADO | `fe1b87e` |
| F16 catálogo de setores/Andon | CORRIGIDO E PROVADO | `05ebe2a` (§2.27) |
| F17 teto de quantidade = planejado | CORRIGIDO E PROVADO | `b403551`; teste legado alinhado em `be1ea9c` |
| F18 ciclo de vida da OP no TOTVS | RECLASSIFICADO / NÃO ERA BUG | regra confirmada; testes `b51cc06` (§2.36) |
| F19 ordem causal da outbox | CORRIGIDO E PROVADO | `4ecac64`, migration 46; testes alinhados em `3620594` e `16061d3` |
| F20 deploy preserva runtime | CORRIGIDO E PROVADO | `7727432`, `412fa13`; `scripts/test_deploy_mirror.ps1` |
| F21 backup/DR | CAPACIDADE IMPLEMENTADA — OPERAÇÃO DEPENDE DA INFRA | `76c2cac`, `1c4842c`; runbook `docs/BACKUP_TESTE.md` |

Correções desta rodada de fechamento:

- `aef9943` — contrato único de datas de período (`422 invalid_date`) também
  para datas com fuso, histórico da Qualidade e relatório personalizado
  (fecha o 500 da §3 item 5, junto com `efa636a`).
- `16061d3` — o script de homologação da Etapa 7A quebrou com `5e91f56`
  (`branch_id` → `branch_ids`) e ainda supunha que as 4 obrigações da OP
  andassem num só ciclo, contrariando F19. Alinhado: um item por OP por ciclo.
- `be1ea9c` — teste de Solda "OP atrasada continua executável" passava operação
  sem quantidade planejada, recusada desde F17.

Comportamento que o operador de infra precisa saber (F19): numa mesma OP, a
outbox entrega **um evento por ciclo**, na ordem; um item em `RETRY`/`ERROR`
segura os seguintes da mesma OP até virar `SENT`. OPs diferentes não se
bloqueiam.

Gate executado no TESTE (nunca no REAL) em 23/09/2026: pytest completo com
PostgreSQL TESTE, vitest, `tsc -b` + `vite build`, E2E Playwright
(`tests/test_e2e_smoke.py` contra o preview `:8010`), bandit, pip-audit,
`npm audit --audit-level=high`, gitleaks, `git diff --check`, versão de schema
(código 49 = TESTE 49), `scripts/test_deploy_mirror.ps1` e backup+verificação+
ensaio de restauração do TESTE (§2.33). Resultado final do pytest após
`16061d3`/`be1ea9c`: 1262 passed, 1 skipped, 2058 subtests, 0 falhas; vitest
183/183; build, auditorias e E2E sem falhas.

## 3. Pendências abertas consolidadas (não bloqueiam código, aguardam decisão)

1. Roteiro de Pintura com posto repetido: uma operação apontável ou duas?
   (§1.3) — decisão de chão de fábrica.
2. ~~Segurança: freio no login principal, IDOR na Qualidade, secrets de sessão
   ausentes no `.env` (§1.2)~~ — **FECHADO**: `779427f` (F6), `_exigir_setor`
   na Qualidade, secrets preenchidos + `f52c37c` (F5). Ver nota em §1.2.
3. Breakpoint de 1024px na Solda: manter 1180px ou reverter para 900px?
   (§1.4) — baixo risco, decisão de uso real.
4. Todas as pendências antigas do `ROADMAP.md` seção 5 (cadastro de recursos,
   Montagem, ingestão do MODELO da Solda, `prazo_entrega` sem origem, filtro
   de setor em Crachás) continuam abertas — nada disso foi resolvido nesta
   janela.
5. ~~**Bug real encontrado por fuzzing (Schemathesis, 20/09/2026):**
   `GET /api/v1/audit/appointments?fim=0263-10-17T17:14:48Z` retornava 500~~
   — **FECHADO** em `efa636a` + `aef9943`: contrato único
   `validated_business_datetime` (`backend/api/dependencies/filters.py`)
   rejeita ano < 2000 ou > ano atual + 1 com `422 invalid_date` e normaliza
   datas com fuso para horário local; aplicado a `analytics_filter` (auditoria,
   OPs e demais filtros gerenciais), histórico da Qualidade e relatório
   personalizado. Testes em `tests/test_web_api.py`.
6. ~~**F18 — ciclo de vida de OP no TOTVS**~~ — **RECLASSIFICADO / NÃO ERA
   BUG** (§2.36): regra de negócio confirmada, execução do MES nunca é
   desfeita pelo ERP; testes em `b51cc06`.
7. **F21 — backup/DR — CAPACIDADE IMPLEMENTADA — OPERAÇÃO DEPENDE DA INFRA.**
   O app entrega backup, verificação e restauração segura
   (`scripts/backup_banco_teste.py`, `76c2cac` + `1c4842c`, §2.33) e o
   runbook `docs/BACKUP_TESTE.md`. Decisões já tomadas: RPO 8/8h; retenção de
   21 backups (7 dias × 3/dia). Ficam com a infraestrutura, não com o
   repositório: agendamento, retenção, cópia fora da VM, monitoramento,
   controle de acesso, ensaio periódico de restauração e aprovação de RPO/RTO.
8. **F4/F9 — ativação operacional:** a role PostgreSQL somente-leitura do
   Dev Observatory foi provisionada e verificada em 23/09/2026 (§2.35) — essa
   parte está feita. Falta apenas registrar o IP/CIDR real do servidor
   Protheus em `GESTOR_TOTVS_SOAP_ALLOWED_SOURCE_CIDRS`; enquanto ausente, o
   receptor SOAP passivo permanece fechado (canal legado — ver nota em
   §2.36 sobre o GPOPSYNC ser o canal ativo hoje).

## 4. O que NÃO fazer (reforço das regras já em `AGENTS.md`)

- Não reabrir a investigação de pull de OP do TOTVS nem a divisão de setores
  da Solda "para conferir" — ambas foram fechadas e homologadas com prova
  real; qualquer dúvida nova exige fato novo, não releitura de hipótese antiga.
- Não tratar os relatórios datados (`docs/*_2026-09-14.md`) como pendência —
  eles são evidência de trabalho já concluído; as pendências reais estão
  destacadas explicitamente nesses relatórios e resumidas na seção 3 acima.
- Não apagar `_quarentena_revisar/` sem o usuário confirmar — nada nela é
  referenciado, mas a decisão de apagar é dele.
