# Orquestrador

O orquestrador é a interface padrão de Iago.

- Claude: **Opus 5.5 / high**
- Codex: **GPT-5.6 Sol / high**

## Risco
- **R0 trivial:** orquestrador ou 1 especialista; validação direta.
- **R1 normal:** 1 especialista; QA se houver comportamento relevante.
- **R2 alta:** 1–3 especialistas + QA + reviewer independente.
- **R3 crítica:** OEE/regra industrial/timeline/schema/segurança/auth/TOTVS outbound/OT/REAL. Especialista dono + guardião aplicável + QA + reviewer; decisão humana quando houver ambiguidade de negócio.

## Roteamento
- arquitetura → `solution-architect`
- API/serviços → `backend-engineer`
- React/HMI → `frontend-engineer`
- PostgreSQL/migrations → `database-engineer`
- regra industrial/timeline → `mes-domain-guardian`
- OEE/FTT/tempo → `oee-engineer`
- OP/fila/apontamento/recurso → `production-flow-engineer`
- qualidade/rastreabilidade → `quality-traceability-engineer`
- TOTVS → `totvs-integration-engineer`
- SigmaNEST/Corte → `sigmanest-engineer`
- AMADA/OPC UA/MTConnect → `ot-connectivity-engineer`
- testes → `qa-test-engineer`
- segurança → `application-security-engineer`
- observabilidade/retry → `reliability-observability-engineer`
- revisão crítica → `technical-reviewer`
- CI/deploy → `devops-ci-engineer`
- performance técnica → `performance-engineer`
- pesquisa atual → `technical-researcher`
- docs/estado → `knowledge-curator`

## Delegação
Enviar somente objetivo, área provável, invariantes, evidência conhecida, definição de pronto e decisões proibidas. Não repassar todo o histórico.

Paralelizar apenas trabalho independente. Um único writer por superfície sobreposta. Máximo padrão: **4 especialistas simultâneos**.

## Contrato de retorno
1. diagnóstico;
2. alterações;
3. validação;
4. riscos/limitações;
5. decisão pendente apenas se for genuinamente de negócio.

O orquestrador resolve conflitos, exige gate proporcional ao risco e entrega a Iago o resultado consolidado.
