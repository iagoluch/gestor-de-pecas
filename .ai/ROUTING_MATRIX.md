# Matriz de Roteamento da IA Workforce

Fonte machine-readable: `.ai/organization.json`. Chamada direta entre `workforce_employee` é proibida; os nomes abaixo representam **colaboração via orquestrador**.

## Regra operacional

- Um owner primário sempre que possível.
- Padrão: 1 owner + 0–2 colaboradores.
- R2/R3 adiciona gates proporcionais.
- `MES Guardian` entra quando semântica industrial pode mudar.
- `Security` entra quando trust boundary relevante muda.
- `Research` somente para incerteza externa atual.
- `Knowledge` após mudança durável de estado/documentação.

## Matriz dos 22 funcionários

| Funcionário | Autoridade / ownership | Colaboradores naturais via orquestrador | Gates padrão |
|---|---|---|---|
| Arquiteto de Soluções | system architecture; cross-layer boundaries; architectural decisions | Engenheiro Backend; Engenheiro Frontend/HMI; Engenheiro de Banco de Dados; Guardião do Domínio MES; Engenheiro de Segurança de Aplicação; Engenheiro de Confiabilidade & Observabilidade; Engenheiro DevOps & CI; Engenheiro de Performance | Engenheiro QA & Testes; Revisor Técnico Independente |
| Engenheiro Backend | FastAPI/API contracts; application services; backend behavior | Arquiteto de Soluções; Engenheiro de Banco de Dados; Guardião do Domínio MES; Engenheiro de Segurança de Aplicação; Engenheiro de Confiabilidade & Observabilidade; Engenheiro QA & Testes; AI/LLM Engineer | Engenheiro QA & Testes |
| Engenheiro Frontend/HMI | React/HMI; browser interaction; accessibility and responsive presentation | Engenheiro Backend; Guardião do Domínio MES; Industrial Analytics & Reporting Engineer; Engenheiro QA & Testes; Engenheiro de Segurança de Aplicação | Engenheiro QA & Testes |
| Engenheiro de Banco de Dados | PostgreSQL schema; migrations; queries and persistence concurrency | Arquiteto de Soluções; Engenheiro Backend; Guardião do Domínio MES; Industrial Analytics & Reporting Engineer; Engenheiro de Confiabilidade & Observabilidade; Engenheiro de Performance; Engenheiro QA & Testes | Engenheiro QA & Testes; Revisor Técnico Independente |
| Guardião do Domínio MES | canonical MES semantics; industrial invariants; physical fact semantics | Engenheiro OEE & Performance Industrial; Engenheiro de Fluxo de Produção; Engenheiro de Qualidade & Rastreabilidade; Industrial Analytics & Reporting Engineer; Engenheiro de Integração TOTVS/Protheus; Engenheiro SigmaNEST & Corte; Engenheiro OT & Conectividade de Máquinas; Engenheiro Backend | Engenheiro QA & Testes; Revisor Técnico Independente |
| Engenheiro OEE & Performance Industrial | OEE/FTT formulas; industrial time classification; OEE loss buckets | Guardião do Domínio MES; Industrial Analytics & Reporting Engineer; Engenheiro de Fluxo de Produção; Engenheiro de Qualidade & Rastreabilidade; Engenheiro de Banco de Dados; Engenheiro QA & Testes | Engenheiro QA & Testes; Revisor Técnico Independente |
| Engenheiro de Fluxo de Produção | production order flow; pointing/resource eligibility; operational state transitions | Guardião do Domínio MES; Engenheiro de Integração TOTVS/Protheus; Engenheiro SigmaNEST & Corte; Engenheiro de Qualidade & Rastreabilidade; Engenheiro Backend; Engenheiro de Banco de Dados; Engenheiro QA & Testes | Engenheiro QA & Testes |
| Engenheiro de Qualidade & Rastreabilidade | quality events; scrap/rework semantics; product genealogy and traceability | Guardião do Domínio MES; Engenheiro de Fluxo de Produção; Engenheiro OEE & Performance Industrial; Industrial Analytics & Reporting Engineer; Engenheiro de Banco de Dados; Engenheiro QA & Testes | Engenheiro QA & Testes |
| Engenheiro de Integração TOTVS/Protheus | TOTVS/Protheus adapters; ERP synchronization; TOTVS outbound | Guardião do Domínio MES; Engenheiro de Fluxo de Produção; Engenheiro de Banco de Dados; Engenheiro Backend; Messaging & Automation Engineer; Engenheiro de Confiabilidade & Observabilidade; Engenheiro de Segurança de Aplicação; Engenheiro QA & Testes | Engenheiro QA & Testes; Engenheiro de Segurança de Aplicação |
| Engenheiro SigmaNEST & Corte | SigmaNEST integration; cutting/nesting plan import; nesting identity and revisions | Guardião do Domínio MES; Engenheiro de Fluxo de Produção; Engenheiro de Banco de Dados; Engenheiro Backend; Industrial Analytics & Reporting Engineer; Engenheiro de Confiabilidade & Observabilidade; Engenheiro QA & Testes | Engenheiro QA & Testes |
| Engenheiro OT & Conectividade de Máquinas | AMADA/VCBox/V-factory connectivity; OPC UA/MTConnect telemetry; OT protocol adapters | Guardião do Domínio MES; Engenheiro de Segurança de Aplicação; Engenheiro de Confiabilidade & Observabilidade; Engenheiro Backend; Engenheiro de Banco de Dados; Pesquisador Técnico; Engenheiro QA & Testes | Engenheiro QA & Testes; Revisor Técnico Independente; Engenheiro de Segurança de Aplicação |
| Engenheiro QA & Testes | test strategy; regression evidence; E2E/integration verification | Revisor Técnico Independente | — |
| Engenheiro de Segurança de Aplicação | application security; auth/session trust boundaries; secrets and dependency security | Arquiteto de Soluções; Engenheiro Backend; Engenheiro de Banco de Dados; Engenheiro OT & Conectividade de Máquinas; Engenheiro de Integração TOTVS/Protheus; AI/LLM Engineer; Messaging & Automation Engineer; Engenheiro DevOps & CI; Engenheiro QA & Testes | Engenheiro QA & Testes; Revisor Técnico Independente |
| Engenheiro de Confiabilidade & Observabilidade | observability; retry/timeout policy; health and failure recovery | Engenheiro Backend; Engenheiro de Banco de Dados; Engenheiro de Integração TOTVS/Protheus; Engenheiro SigmaNEST & Corte; Engenheiro OT & Conectividade de Máquinas; Messaging & Automation Engineer; Engenheiro DevOps & CI; Engenheiro de Performance | Engenheiro QA & Testes |
| Revisor Técnico Independente | independent R2/R3 review; material defect review | — | — |
| Engenheiro DevOps & CI | CI/CD; build and delivery automation; development toolchain | Arquiteto de Soluções; Engenheiro de Segurança de Aplicação; Engenheiro de Confiabilidade & Observabilidade; Engenheiro QA & Testes; Engenheiro de Performance | Engenheiro QA & Testes |
| Engenheiro de Performance | performance profiling; performance baselines; hot-path optimization | Engenheiro Backend; Engenheiro Frontend/HMI; Engenheiro de Banco de Dados; Engenheiro de Confiabilidade & Observabilidade; Engenheiro DevOps & CI; Engenheiro QA & Testes | Engenheiro QA & Testes |
| Pesquisador Técnico | current external technical research; official documentation evidence | — | — |
| Curador de Conhecimento | canonical project documentation; status and decision documentation | — | — |
| AI/LLM Engineer | AI runtime; provider adapters; prompt/tool contracts; LLM evaluation | Guardião do Domínio MES; Engenheiro de Segurança de Aplicação; Engenheiro Backend; Pesquisador Técnico; Engenheiro de Confiabilidade & Observabilidade; Messaging & Automation Engineer; Engenheiro QA & Testes | Engenheiro QA & Testes |
| Industrial Analytics & Reporting Engineer | analytics projections; report contracts/artifacts; management insights | Engenheiro OEE & Performance Industrial; Guardião do Domínio MES; Engenheiro de Qualidade & Rastreabilidade; Engenheiro de Fluxo de Produção; Engenheiro de Banco de Dados; Engenheiro Backend; Engenheiro Frontend/HMI; Engenheiro QA & Testes | Engenheiro QA & Testes |
| Messaging & Automation Engineer | messaging channels; notification routing/presentation; communication automation | Engenheiro Backend; Engenheiro de Confiabilidade & Observabilidade; Engenheiro de Segurança de Aplicação; AI/LLM Engineer; Industrial Analytics & Reporting Engineer; Engenheiro de Integração TOTVS/Protheus; Engenheiro QA & Testes | Engenheiro QA & Testes |

## Chamadas diretas

`workforce_employee → workforce_employee`: **proibido**.

Exceção atual: `frontend-engineer` pode chamar diretamente os quatro `specialist_subagent` Impeccable declarados no `organization.json`.

## Exemplos

### OEE calculado incorretamente
Owner: `oee-engineer`. Colaboração: `mes-domain-guardian`, e `industrial-analytics-reporting-engineer` se projeções forem afetadas. Gates: QA + reviewer para R3.

### Relatório executivo
Owner: `industrial-analytics-reporting-engineer`. Colaboração: OEE/MES/Frontend apenas conforme as métricas e superfície. Gate: QA.

### IA respondendo OEE errado
Owner provável: `ai-llm-engineer` se o erro estiver em tool/prompt/provider. `oee-engineer` e `mes-domain-guardian` validam a verdade industrial. Corrigir prompt não pode mascarar dado/fórmula errada.

### Telegram com IA
Owner do canal: `messaging-automation-engineer`; owner da inteligência: `ai-llm-engineer`. Security entra se token/webhook/permissão mudar.

### Nova máquina AMADA
Owner: `ot-connectivity-engineer`. Colaboração: MES Guardian, Security e Reliability conforme escopo. Escrita OT continua exigindo autorização humana.

### TOTVS enviando recurso incorreto
Owner: `totvs-integration-engineer`. Colaboração: Production Flow e MES Guardian se elegibilidade/semântica de recurso estiver envolvida.
