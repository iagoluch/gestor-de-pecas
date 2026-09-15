# Gestor de Peças

MES industrial Web para execução, rastreabilidade, gestão e inteligência da
manufatura. O frontend oficial é React/TypeScript; o backend é FastAPI/Python e
as regras industriais permanecem nos serviços/domínio canônicos.

**Workspace padrão de desenvolvimento e homologação:**

```text
Gestor de Peças - Area de Testes
```

A direção oficial do projeto está em [`ROADMAP.md`](ROADMAP.md). Relatórios
datados são evidência histórica e não devem substituir o roadmap atual.

## Arquitetura

```text
React / TypeScript
        ↓ HTTP + SSE
FastAPI (backend/api)
        ↓
serviços / contratos (mes/services, mes/contracts)
        ↓
domínio / analytics (mes/domain, mes/analytics)
        ↓
persistência PostgreSQL (app/database)
```

Responsabilidades:

- **TOTVS/Protheus:** planejamento corporativo e dados mestres confirmados;
- **SigmaNEST:** planejamento específico de Corte — tarefa, plano, nesting e a
  composição de produtos de cada agrupamento, sincronizado em leitura por
  `scripts/sincronizar_sigmanest.py`;
- **Gestor:** execução real, eventos, tempos, quantidades, rastreabilidade,
  analytics e inteligência;
- **PostgreSQL:** banco da aplicação;
- **Frontend:** apresentação/interação, sem regra produtiva paralela.

Não existe entrypoint operacional desktop/PySide6. O produto é Web-only.

## Estado da integração TOTVS

Em 27/08/2026, no ambiente TESTE, estão homologados:

- SOAP 1.1 `PcfIntegService.receiveMessage`;
- `WhoIs` do PCPA109;
- `ProductionOrder/upsert` do PCPA111;
- persistência no `gestor_pecas_test`, migration 22;
- resposta `TOTVSMessage/ResponseMessage` com
  `ProcessingInformation/Status=OK`, reconhecida pelo Protheus;
- OP real `A9716901001` recebida no banco TESTE oficial.

A OP real de referência trouxe 5 atividades; 2 foram projetadas com mapeamento
seguro (`PLASMA/Corte` e `CNC-01/Usinagem`). As demais possuem tratamento
funcional explícito e permanecem auditáveis sem virar tarefa do operador. Ver
`docs/INTEGRACAO_TOTVS_PRODUCTION_ORDER_V1.md`.

Desde a Etapa 3, essa projeção entra na fila e na Tela do Operador já
existentes, usando exclusivamente os serviços canônicos. A lógica de apontamento
do Gestor é canônica: a integração TOTVS fornece planejamento ao domínio
existente e não cria uma segunda lógica operacional.

O retorno de execução Gestor → TOTVS foi homologado nas Etapas 5/5C e ganhou
outbox transacional com retry; o envio automático nasce desligado. Ver
`docs/INTEGRACAO_TOTVS_OUTBOUND_ETAPA5.md` e
`docs/INTEGRACAO_TOTVS_OUTBOX_ETAPA6.md`.

Desde as Etapas 6.1/6.2, uma OP digitada pelo operador que ainda não exista no
Gestor é buscada pelo endpoint mínimo `GPOPSYNC` e carregada pelo **mesmo**
pipeline inbound — não há segunda implementação de importação de OP. A correção
foi compilada/publicada no Protheus TESTE e o `MATI650` inline foi homologado em
03/09/2026.

A Etapa 7A concluiu a homologação controlada de concorrência, execução canônica,
outbox, retry, restart, lease e idempotência. A Etapa 7B substituiu somente a
fronteira controlada pelo transporte real: a OP `00615903001` percorreu MISS →
GPOPSYNC/MATI650 real → ingestão canônica → PostgreSQL → consulta operacional,
em uma chamada de 1,317 s. O caso matriz `10795102002`, existente no ERP mas sem
roteiro, permanece sem operações inventadas e recebe o estado explícito
`sem_roteiro`. Ver `docs/INTEGRACAO_TOTVS_OP_SOB_DEMANDA_ETAPA61.md` e
`docs/evidencias/TOTVS_ETAPA7B_HOMOLOGACAO_REAL_2026-09-03.md`.

## Bancos do ambiente atual

No ambiente local de trabalho:

```text
gestor_pecas       → REAL preservado
gestor_pecas_test  → TESTE oficial
postgres           → administrativo
```

Os antigos bancos de simulação/homologação foram removidos após dumps
verificados e restauráveis. Menções aos nomes antigos em relatórios datados são
históricas.

Este checkout `Area de Testes` resolve a conexão operacional atual pelo caminho
de teste (`TEST_DATABASE_URL`). Não assumir o banco efetivo apenas pela `.env`:
em homologações críticas, validar a conexão em runtime.

## Simulação de fábrica

`scripts/simular_fabrica.py` executa um turno industrial completo sobre o
`gestor_pecas_test`, operando a fábrica **pela API** (`/operator`, `/cutting`,
`/highlight`, `/quality`) e pelos serviços canônicos — nunca por SQL de
apontamento. A configuração oficial fica em `config/simulacao_fabrica.json` e as
evidências em `docs/evidencias/simulacao_fabrica/<run_id>/`.

O relógio virtual pertence ao processo Web (`GESTOR_SIMULATION_MODE`,
`GESTOR_SIMULATION_NOW`, `GESTOR_SIMULATION_TIME_SCALE`); o simulador só o lê e,
com `--pause`/`--resume`, o congela pelo endpoint `/system/simulation/clock`.

```bash
python scripts/simular_fabrica.py --dry-run      # preflight completo, sem escrever
python scripts/simular_fabrica.py --reset --speed 16
```

O preflight recusa banco diferente de `gestor_pecas_test`, schema divergente,
timezone inesperado e qualquer sinal de outbound TOTVS habilitado.

## Funcionalidades principais

- login, sessão, autorização por perfil e proteção CSRF;
- posto do operador com OP, operação, roteiro, fila, recursos e crachá;
- Produção, Parada, Setup, Retrabalho, retomada e finalização;
- Corte/Nesting e Destaque;
- quantidades boas, refugo e retrabalho separados;
- estado físico canônico do recurso e interrupção automática de turno;
- histórico, auditoria e rastreabilidade;
- Andon TV e visão gerencial;
- OEE, FTT, KPI explicável, dashboard de exceções e analytics;
- relatórios CSV/Excel;
- IA Industrial via Groq com ferramentas canônicas do backend.

## Requisitos

- Python 3.14+;
- Node.js compatível com `web/package-lock.json`;
- PostgreSQL 14+ ou a instância prevista pelo `compose.yaml`.

## Configuração

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

Set-Location web
npm ci
Set-Location ..

Copy-Item .env.example .env
```

Nunca versione `.env`, tokens ou credenciais.

## Desenvolvimento Web

Backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend:

```powershell
Set-Location web
npm run dev
```

O Vite encaminha `/api` para o backend local.

## Build Web integrado

```powershell
Set-Location web
npm run build
Set-Location ..
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

Quando `web/dist/index.html` existe, o FastAPI entrega o SPA e mantém a API em
`/api/v1`. OpenAPI: `/api/docs`.

## Testes

Suíte Python:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Os testes do contrato SigmaNEST (`tests/test_sigmanest_planning.py`) usam
fixtures fiéis à auditoria e **não** acessam o banco SigmaNEST.

Integrações PostgreSQL devem usar exclusivamente `TEST_DATABASE_URL` apontando
para `gestor_pecas_test` ou banco temporário explicitamente criado pelo teste.
Seeders históricos de simulação não devem ser apontados casualmente para o banco
TESTE oficial.

Frontend:

```powershell
Set-Location web
npm test
npm run build
```

### Dívidas de teste conhecidas em 27/08/2026

No último relatório após a limpeza dos bancos, a suíte completa possuía duas
falhas conhecidas que devem ser corrigidas sem mascaramento:

- `test_oee_evolution_equivalence`: dependência de massa histórica removida;
  deve tornar-se autossuficiente/determinístico, não ser apenas `skip`;
- `test_web_api`: assert dependente da data fixa `2026-08-26`; deve usar data ou
  relógio controlado.

## Segurança e integração corporativa

- frontend não calcula regra industrial;
- operações produtivas relacionadas são transacionais;
- histórico produtivo não possui edição/exclusão genérica;
- `.env`, tokens, credenciais, caches e `.venv` não entram em release;
- nenhuma integração deve escrever diretamente em tabelas TOTVS;
- Quick Tunnel/`trycloudflare.com` é somente homologação, nunca endpoint de
  produção;
- TESTE e REAL devem permanecer isolados.

## Documentação principal

- `ROADMAP.md` — direção oficial e próxima etapa;
- `docs/STATUS_ATUAL.md` — o que aconteceu depois da última atualização do
  ROADMAP; ler antes de assumir que o ROADMAP está em dia;
- `AGENTS.md` — regras obrigatórias para agentes;
- `docs/INTEGRACAO_TOTVS_PRODUCTION_ORDER_V1.md` — contrato inbound homologado;
- `docs/HOMOLOGACAO_TOTVS_PRODUCTION_ORDER_V1_20260826.md` — histórico da
  homologação iniciada em 26/08 e concluída ao vivo em 27/08;
- `docs/INTEGRACAO_CORPORATIVA_TOTVS_PENDENTE.md` — fronteira e pendências de
  retorno ao TOTVS;
- `docs/INTEGRACAO_CORTE_SIGMANEST.md` — Qlik removido da arquitetura alvo e
  sincronização comprovada do banco SigmaNEST para a fila de Corte;
- `docs/DESCOBERTAS_SIGMANEST_20260827.md` — engenharia reversa do SigmaNEST;
- `docs/AUDITORIA_EXECUCAO_GERENCIAL_ETAPA_4A.md` — fonte canônica de cada
  informação entre execução e indicadores;
- `docs/SIMULACAO_INTEGRAL_FABRICA_ETAPA_4B.md` — simulação com a fábrica
  operando: turno, H2, limite 21:30, virada de dia, OP TOTVS apontada e o gap
  de cadastro de recursos registrado para saneamento futuro;
- `docs/CADASTRO_RECURSOS_E_POSTOS.md` — identidade canônica do recurso,
  relação posto ↔ máquina por setor, matriz de elegibilidade e as pendências
  de cadastro que dependem da Manufatura;
- `docs/OPERATOR_SCREEN_FLOW.md` — fluxo operacional;
- `docs/REGRAS_MANUFATURA_CANONICAS.md` — regras funcionais validadas.

## Autor

Desenvolvido por **Iago Luchtenberg da Silva**.
