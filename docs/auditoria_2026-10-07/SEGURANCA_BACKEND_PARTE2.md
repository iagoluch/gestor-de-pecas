# Auditoria de segurança do backend — parte 2 (2026-10-08)

Responsável: `application-security-engineer`. Continuação de `SEGURANCA_BACKEND.md` (A1/A2 já corrigidos).
Escopo: A8, A9 e segunda passada só leitura (corridas, cliente TOTVS WSPCP, cliente SQL SigmaNEST).

Status: CONCLUÍDA. A8 e A9 corrigidos com teste; segunda passada só leitura sem correção (nenhum achado pequeno o bastante
para corrigir sem decisão ou migration). Nada commitado; `.env`, banco, API e migrations intocados.

Arquivos alterados:
- `mes/services/cut.py` (`finalizar` com `maquina`)
- `backend/api/routers/cutting.py` (repassa `maquina=resource`)
- `backend/api/routers/dev_observatory.py` (`LOGGER` + mensagem fixa em `observatory_page`)
- `tests/test_cut_service.py`, `tests/test_web_api.py`, `tests/test_dev_observatory.py` (testes novos)

## A8 — Corte: `appointment_id` do "Finalizado" sem amarração ao recurso — CORRIGIDO

- Confirmado: `mes/services/cut.py` `finalizar()` procurava o ID em `self.listar_fila()` (todas as máquinas);
  `backend/api/routers/cutting.py` não repassava o `resource` validado.
- Correção: `CutService.finalizar(apontamento_id, maquina=None)`. Com `maquina`, a busca usa `listar_fila(maquina)`;
  máquina sem mapeamento SigmaNEST é recusada (sem isso o filtro viraria "todas"). A rota passa `maquina=resource`.
  Sem `maquina` o comportamento é o anterior (chamadores internos/testes).
- Testes: `tests/test_cut_service.py::test_finalizar_recusa_apontamento_de_outra_maquina` e trecho novo em
  `tests/test_web_api.py::test_fluxo_web_corte_preserva_fila_automatica_e_nesting` (Plasma tentando fechar nesting do Laser → 409, apontamento segue "Em processo"). Ambos falhavam antes.

- Validação: `GESTOR_EXPECTED_DATABASE=gestor_pecas_test python -m pytest -q tests/test_cut_service.py tests/test_web_api.py`
  → **95 passed, 78 subtests passed** (override só no comando, `.env` intocado).
  Observação: sem o override, 2 testes Postgres de `tests/test_totvs_operator_queue.py` falham por guarda de ambiente
  ("banco ativo 'gestor_pecas_test', esperado 'gestor_pecas'"), idêntico com e sem a mudança — não é regressão.

## A9 — Mensagens técnicas em superfícies restritas — CORRIGIDO onde havia vazamento a não autenticado

- `backend/api/routers/dev_observatory.py` (`observatory_page`): era o único ponto que devolvia `str(exc)` **antes da autenticação**
  (qualquer máquina da rede interna). Exceção de conexão do psycopg traz host, porta, usuário e banco. Agora: mensagem fixa
  "Backend indisponível." + `LOGGER.exception`. Validação: `python -m pytest -q tests/test_dev_observatory.py` → 26 passed. Teste: `tests/test_dev_observatory.py::test_pagina_nao_expoe_excecao_bruta_antes_do_login`
  (verificado por mutação: reintroduzir `{exc}` faz o teste falhar).
- Mantidos (sem correção, público restrito e autenticado):
  - `dev_observatory.py` `_database_for` (`AppError(..., str(exc))`), status e relatório (`"error": str(exc)`): só sessão do Dev Observatory, bloqueado no host público.
  - `system.py` `/system/rebuild-frontend`: saída do build só para admin + CSRF.
- Verificado sem vazamento ao operador:
  - `mes/services/task_lookup.py:53`: monta `f"Falha ao consultar o catálogo local: {exc}"`, mas o único consumidor
    (`highlight.py:_task_payload`) descarta a mensagem e responde 404 fixo. Latente (ver R5 abaixo).
  - `mes/integrations/totvs/on_demand.py`: grava `str(exc)` no banco; o retorno ao operador usa só o código.
  - Outbox TOTVS (`totvs_outbox_worker`, `outbound_enqueue`): texto vai só para a tabela da outbox; nenhuma rota de API o expõe hoje.
  - `chamadas.py`, `management.py`, `operator_flow.py:1550`: `str(exc)` de `ValueError` de validação de domínio, não de driver.

---

## Segunda passada (só leitura)

Legenda igual à parte 1: **[Certo]** = confirmado lendo o código; **[Provável]** = inferência não reproduzida.

### R1. Baixo/Médio — Início de apontamento em recurso não exclusivo (fora da Solda) sem trava: duplo "Iniciar" pode abrir dois apontamentos da mesma OP/operação [Provável]

- **Evidência:** `app/database/database.py:2184-2200` (`enfileirar_apontamento_operacional`). A transação só toma trava em dois casos:
  Solda (`_operacao_em_outra_estacao_tx`, trava por OP+operação) e recurso exclusivo (`_travar_recurso_tx`, BK-03).
  Nos demais setores com recurso não exclusivo, a checagem de "já existe apontamento aberto" é feita pelo
  `OperatorFlowService` (`mes/services/operator_flow.py:~1322`) em outra transação, antes do `INSERT`. Não achei
  índice único parcial em `apontamentos_operacionais` que segure a duplicata.
- **Cenário:** duplo toque em "Iniciar" (ou dois terminais do mesmo setor) na mesma OP/operação → duas linhas abertas;
  produção pode ser apontada em duplicidade e o envio ao TOTVS reflete isso. Integridade, não escalada de acesso.
- **Ação sugerida:** reaproveitar a trava por (OP, operação) da Solda para todos os setores dentro da mesma transação
  (sem migration), com teste de duas chamadas concorrentes no Postgres de teste. Confirmar antes se recurso não exclusivo
  aceita, por regra, a mesma OP/operação duas vezes (decisão de negócio). Não corrigido: depende dessa regra.

### R2. Baixo — Criação de usuário inativo em duas transações [Certo]

- **Evidência:** `backend/api/routers/management.py:504-512`: `criar_usuario` grava `ativo=TRUE`
  (`app/database/database.py:421-437`) e só depois `ativar_desativar_usuario(usuario_id, False)`.
- **Cenário:** se a segunda chamada falhar (banco caindo entre as duas), a conta pedida como inativa fica ativa, com a
  senha definida pelo admin. Janela curta e quem conhece a senha é o próprio admin.
- **Corrida no nome:** OK. `uq_usuarios_nome` (`app/database/migrations.py:160`) + `UniqueViolation` → `None` → 409.
  Observação: a unicidade é sensível a maiúsculas ("Joao" e "joao" coexistem). Informativo.
- **Ação sugerida:** passar `ativo` para o `INSERT` de `criar_usuario` (uma transação). Pequeno, mas muda a assinatura do
  repositório e do `FakeDatabase`; deixado para decisão.

### Corridas verificadas e OK [Certo]

- Transição de apontamento operacional: `SELECT ... FOR UPDATE` + máquina de estados + trava de recurso exclusivo
  (`database.py:2455-2489`). Já existe teste de duas finalizações simultâneas (`test_wave6b_gate_setup_qualidade.py:931`).
- Corte: início com `ON CONFLICT (plano_hash) DO NOTHING` (`database.py:1387`); fim com `UPDATE ... WHERE status='Em processo'`
  (`database.py:1422`); avanço de nesting com `FOR UPDATE` (`database.py:1463`).

### R3. Médio (decisão já registrada, BK-15) — SigmaNEST confia em qualquer certificado TLS por padrão [Certo]

- **Evidência:** `backend/integrations/sigmanest_sqlserver.py:83-89`: `SIGMANEST_TRUST_SERVER_CERTIFICATE` vale `yes` por padrão.
- **Cenário:** quem estiver no caminho de rede entre o Gestor e o SQL Server do SigmaNEST apresenta um certificado
  qualquer e lê o tráfego TDS. Com login SQL (`UID`/`PWD`), isso inclui a credencial.
- **Ação sugerida:** instalar a CA interna e usar `SIGMANEST_TRUST_SERVER_CERTIFICATE=no` (+ `SIGMANEST_HOSTNAME_IN_CERTIFICATE`
  se o servidor for IP). É mudança de `.env`/infra, não de código.

### SigmaNEST SQL — verificado e OK [Certo]

- Injeção: as duas consultas são constantes com `?` (`sigmanest_sqlserver.py:131-168`, `219-221`).
- Timeouts: `Connect Timeout` no DSN (padrão 10 s) e timeout de consulta obrigatório, com falha fechada se não aplicar (`:116-127`, `:190-196`).
- Menor privilégio no cliente: `readonly=True`, `ApplicationIntent=ReadOnly`, `autocommit` (`:90`, `:185`).
- Segredos: `UID`/`PWD` escapados por `_odbc_value`; o log (`mes/services/sigmanest_refresh.py:121`) registra a exceção do driver,
  que não traz a senha; o texto bruto sai para a gestão (`/cutting/sync/diagnostico`) e não para o operador (A2).
- `mask_dsn` (`:104`) existe mas não tem chamador em produção. Informativo.

### TOTVS WSPCP (`backend/integrations/totvs_wspcp.py`) — verificado e OK [Certo]

- TLS: `verify=True` por padrão; só desliga por `GESTOR_TOTVS_OUTBOUND_VERIFY_TLS` explícito (`:63`, `:127`, `:210-213`).
- Timeout: 30 s por padrão, configurável (`:58`, `:126`, `:186-192`).
- Auth: Basic só com modo explícito; credencial sem modo é recusada (`:218-236`). A senha vai no header, não na URL nem em log.
- Injeção XML: o XML de negócio vai em CDATA com `]]>` neutralizado (`:40`); o ACK é lido por `parse_wspcp_ack` (defusedxml, parte 1).
- Mensagens de erro (`:141`, `:151`) vão para a outbox no banco; nenhuma rota de API as expõe. `raw_response` também fica só no banco.
- Baixo/informativo: o corpo da resposta não tem teto de tamanho (`response.text`), mas o par é o Protheus interno.

### R5. Informativo — mensagem latente em `task_lookup`

- `mes/services/task_lookup.py:53` monta `f"Falha ao consultar o catálogo local: {exc}"`. Hoje o único consumidor
  (`backend/api/routers/highlight.py:113-116`) descarta e responde 404 fixo, então não vaza. Se um consumidor futuro repassar
  `lookup.message`, vaza texto do driver. Também mascara falha de banco como "tarefa não encontrada".
- **Ação sugerida:** mensagem fixa no `message` (o `logging.exception` já existe). Não corrigido: não há vazamento atual.

## Resumo dos achados restantes

| ID | Severidade | Tipo | Ação |
|----|-----------|------|------|
| R1 | Baixo/Médio | Integridade (corrida no Início, recurso não exclusivo) | Decisão de regra + trava por OP/operação |
| R3 | Médio | TLS SigmaNEST confia em qualquer certificado | Infra/.env (CA interna) |
| R2 | Baixo | Usuário inativo criado em 2 transações | Passar `ativo` no INSERT |
| R5 | Informativo | Mensagem latente com exceção | Mensagem fixa |
| A3–A7 | ver parte 1 | — | Inalterados nesta rodada |
