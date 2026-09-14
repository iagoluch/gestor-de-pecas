# ETAPA 6 — outbox transacional, retry e confiabilidade do outbound TOTVS

Atualizado em: 01/09/2026
Ambientes autorizados: `gestor_pecas_test` e TOTVS TESTE (`Csed4j_dev`)
Status: **CONCLUÍDA**, com falha controlada comprovada no ambiente real de TESTE.
Evidência: `docs/evidencias/TOTVS_OUTBOX_ETAPA6_2026-09-01.md` e o JSON bruto ao lado.

A Etapa 5 continua intacta: contratos, mapper, parser de ACK, gateway SOAP,
regra do marco terminal e bloqueio de retrabalho não foram reescritos.

## 1. Problema resolvido

Antes, o outbound só existia como comando manual síncrono. Agora:

```text
AÇÃO OPERACIONAL
      ↓
transação PostgreSQL
├─ evento canônico
├─ quantidades canônicas
├─ estado local
└─ INSERT totvs_outbox          ← mesma transação
      ↓
COMMIT  → o operador recebe sucesso aqui
      ↓
worker independente
      ↓
WSPCP → ACK
   ├─ OK / duplicado          → SENT
   ├─ transitório             → RETRY com backoff
   ├─ autenticação/config     → RETRY limitado e então ERROR
   └─ funcional (Status=ERROR)→ ERROR sem retry
```

Nenhuma chamada SOAP participa da transação do operador. Com o TOTVS fora, o
apontamento continua sendo aceito, registrado e visível; apenas a entrega fica
pendente.

## 2. Tabelas — migration 19

`totvs_outbox`

| Campo | Papel |
|---|---|
| `event_type`, `aggregate_type`, `aggregate_id` | identidade do fato de origem |
| `canonical_event_id` | FK para `eventos_apontamento_operador` (`ON DELETE CASCADE`) |
| `production_order`, `operation_code` | contexto industrial consultável |
| `idempotency_key` | **UNIQUE no banco** — a mensagem lógica |
| `transaction`, `payload_xml`, `payload_context` | a mensagem exata do instante do fato |
| `status` | `PENDING`, `SENDING`, `RETRY`, `SENT`, `ERROR` |
| `attempts`, `max_attempts`, `next_attempt_at` | política de retry persistida |
| `lease_owner`, `lease_expires_at` | reserva do worker e recuperação de abandono |
| `last_http_status`, `last_ack_status`, `last_delivery_class` | desfecho da última tentativa |
| `last_error_code`, `last_error_message` | diagnóstico, truncado em 2000 caracteres |
| `internal_id` | `InternalId` devolvido pelo Protheus |
| `created_at`, `updated_at`, `sent_at`, `last_attempt_at` | linha do tempo |

Constraints que sustentam a garantia, e não apenas a intenção:

- `uq_totvs_outbox_idempotency_key UNIQUE (idempotency_key)`;
- `ck_totvs_outbox_status` restringe os cinco estados;
- `ck_totvs_outbox_payload`: `payload_xml IS NOT NULL OR status = 'ERROR'`;
- `ck_totvs_outbox_lease`: `SENDING` obriga `lease_expires_at`;
- índices parciais `idx_totvs_outbox_due` (fila elegível) e
  `idx_totvs_outbox_lease` (recuperação).

`totvs_outbox_attempts` guarda **cada** tentativa (`outbox_id`,
`attempt_number` único por item, `started_at`, `finished_at`, `outcome`,
`delivery_class`, `http_status`, `ack_status`, `error_code`, `error_message`,
`internal_id`, `worker`). O último erro nunca apaga a evidência anterior.

Nenhuma tabela paralela de roteiro, quantidade ou apontamento foi criada.

## 3. Garantia transacional

`Database.transicionar_apontamento_operador` chama
`_enfileirar_outbound_totvs_tx` **dentro** da mesma transação, depois de gravar
o evento e as quantidades canônicas — porque o read model outbound lê essas
quantidades — e antes do `COMMIT`.

O read model (`buscar_evento_canonico_outbound_totvs`,
`buscar_marco_terminal_outbound_totvs`) passou a aceitar um `cursor` externo.
Sem isso, uma conexão nova não enxergaria as linhas ainda não commitadas.
Continua sendo apenas `SELECT`.

### A distinção que sustenta a garantia

**Não existe `SAVEPOINT` nesta função.** Uma versão anterior usava um para
impedir que o enqueue derrubasse o apontamento; isso estava errado e foi
removido, porque permitia exatamente o cenário proibido: apontamento commitado
sem a sua obrigação outbound, uma perda que nenhum worker, retry ou
reprocessamento consegue recuperar.

| Situação | Efeito | Por quê |
|---|---|---|
| WSPCP fora, timeout, rede caída | **COMMIT normal**, item `PENDING`, worker tenta depois | a comunicação externa não acontece nesta transação |
| `INSERT` na `totvs_outbox` falha | **ROLLBACK da transação inteira** | a obrigação não pôde ser registrada duravelmente |
| Fato canônico não pôde ser lido para decidir se há obrigação | **ROLLBACK** | não dá para afirmar que não havia obrigação |
| `ON CONFLICT DO NOTHING` e a chave também não existe | **ROLLBACK** (`DatabaseIntegrityError`) | "duplicata" nunca pode virar "obrigação ausente" |
| Falta `WasteCode`/`StopReasonCode` | **COMMIT normal**, item `ERROR` bloqueado | não é falha de persistência: a obrigação **fica registrada**, com os valores |
| Recurso divergente | **COMMIT normal**, item `ERROR` bloqueado | idem |
| Outbox desabilitada por configuração | **COMMIT normal**, sem item | não existe obrigação a registrar |

A indisponibilidade do ERP não derruba a operação. A impossibilidade de
registrar duravelmente a obrigação de integração derruba a transação.

## 4. Eventos que geram outbox

Somente contratos homologados na Etapa 5:

| Fato canônico | Mensagem | Observação |
|---|---|---|
| `parcial` com quantidade | `ProductionAppointment`, `CloseOperation=false` | — |
| `finalizado` | `ProductionAppointment`, `CloseOperation=true` | — |
| refugo junto com o apontamento | `ProductionAppointment` + `WasteCode` | exige código TOTVS configurado |
| execução da OP concluída | `ProductionAppointment` terminal | regra do marco terminal inalterada |
| retomada/encerramento após `parada` | `StopReport` fechado | exige `StopReasonCode` configurado |
| início com quantidade zero | `ProductionAppointment` zero | **opt-in** por `GESTOR_TOTVS_OUTBOX_ZERO_START_ENABLED` |
| `parada` ainda aberta | nenhuma | o contrato exige início e fim |
| retrabalho | nenhuma | continua bloqueado, sem destino comprovado |
| OP sem `CompanyId`/`BranchId` | nenhuma | não veio do TOTVS, não tem para onde voltar |
| ingestão de `ProductionOrder` | nenhuma | entrada de planejamento não gera saída |

`WasteCode` e `StopReasonCode` pertencem a cadastros do Protheus e **não são
inferidos** do texto do Gestor. Quando faltam, o item entra como `ERROR`
bloqueado, com `payload_xml` nulo e motivo explícito — visível e reprocessável,
em vez de perdido ou convertido por semelhança de nome.

### Refugo e parada ficam guardados para lançar depois

Uma observação de contrato, porque a dúvida já surgiu: **refugo e parada entram
sim no TOTVS**. A Etapa 5 provou isso em envio real no TESTE —
`ScrapQuantity` com `WasteCode=RP` (InternalId 783160) e dois `StopReport` com
`StopReasonCode` `0010` e `0018` (783161 e 783162). O que falta não é contrato:
é o mapa entre o motivo escrito pelo operador no Gestor e o código do cadastro
Protheus.

Enquanto esse mapa não existir, nada se perde. O item bloqueado guarda em
`payload_context` os **valores**, não apenas o aviso de que faltou configuração:

* refugo — `scrap_quantity`, `good_quantity`, `scrap_reason` (o texto original
  do operador), `close_operation`, OP, operação, recurso, item, empresa/filial,
  depósito, janela de tempo e operador;
* parada — `stop_started_at`, `stop_ended_at` (o intervalo fechado que o
  `StopReport` exige), `stop_reason_gestor`, `stop_resource_status_code`,
  `stop_interruption_planned`, recurso e empresa/filial.

Configurados os cadastros, `scripts/totvs_outbox_admin.py reprocessar --id <id>`
remonta a mensagem a partir do MESMO fato canônico imutável e a fila entrega —
o refugo e a parada de hoje chegam ao Protheus depois, sem reabertura de
apontamento e sem nova identidade.

## 5. Worker e concorrência

`mes/services/totvs_outbox_worker.py`, com separação estrita entre ENQUEUE e
DELIVERY. Um ciclo:

1. recupera `SENDING` com lease expirado;
2. reserva um lote com
   `SELECT ... FOR UPDATE SKIP LOCKED` seguido de `UPDATE ... SET status='SENDING'`,
   incrementando `attempts` e gravando `lease_owner`/`lease_expires_at`;
3. **fecha a transação de reserva**;
4. faz o POST fora de qualquer transação PostgreSQL aberta;
5. classifica HTTP + SOAP + ACK;
6. grava o desfecho e a linha de tentativa, liberando a reserva.

Dois workers simultâneos nunca reservam a mesma linha: quem não obtém o lock a
pula. Comprovado com duas conexões concorrentes em teste.

Execução: dentro do backend (`GESTOR_TOTVS_OUTBOX_WORKER_ENABLED`, task
`gestor-totvs-outbox-worker` no `lifespan`) ou fora dele, pelo CLI. É o mesmo
`TotvsOutboxWorker` nos dois casos.

## 6. Idempotência

A chave determinística da Etapa 5 virou a identidade da mensagem:

- `ProductionAppointment` e `StopReport`: `uuid5` sobre o id do evento canônico;
- marco terminal: `uuid5` sobre OP + operação terminal.

Ela é persistida **antes** do primeiro envio e é `UNIQUE` no banco. Retry,
timeout, reinício, recuperação de lease e reprocessamento manual reutilizam
exatamente a mesma chave e o mesmo XML. O enqueue usa `ON CONFLICT DO NOTHING`,
então uma segunda tentativa de enfileirar a mesma mensagem lógica — inclusive
o terminal — é recusada pelo banco sem abortar a transação do operador.

O transporte é **at least once**. A idempotência aproxima o efeito de uma única
vez; não existe garantia de *exactly once* e este trabalho não a afirma.

## 7. Classificação de erro e backoff

`mes/integrations/totvs/outbox.py`, domínio puro:

| Situação | Classe | Política |
|---|---|---|
| ACK `Status=OK` ou duplicidade código 3 | `success` | `SENT` |
| ACK HTTP 200 com `Status=ERROR` | `functional` | `ERROR` imediato, sem retry |
| timeout, conexão recusada, rede | `transient` | retry até `max_attempts` (12) |
| HTTP 408/425/429/500/502/503/504/507/509 | `transient` | idem |
| HTTP 401/403/407, ou Fault com `AUTHENTICATION`/`NOT AUTHORIZED` | `authentication` | retry limitado a 3 e então `ERROR` |
| HTTP 4xx de rota/publicação | `authentication` | idem |
| HTTP 200 com corpo fora do contrato | `protocol` | retry limitado a 3, mesma chave |

O Fault textual importa porque o WSPCP TESTE responde credencial inválida com
HTTP **500**, não 401/403. Sem essa leitura, senha errada entraria em retry
longo se passando por indisponibilidade.

Backoff persistido em `next_attempt_at`: **1, 2, 5, 10, 30 e 60 minutos**, com o
último degrau repetido. Doze tentativas cobrem cerca de oito horas.

## 8. Recuperação

- **Startup:** o primeiro ciclo do worker recupera `SENDING` abandonado, entrega
  `PENDING` antigo e retoma `RETRY` vencido, sem intervenção manual.
- **`SENDING` abandonado:** lease expirado devolve o item para `RETRY` com a
  MESMA chave e registra uma tentativa `abandonado` no histórico.
- **Shutdown:** a task é cancelada e para de reservar; o que estiver em
  `SENDING` volta sozinho por expiração de lease.

## 9. Reprocessamento manual

`mes/services/totvs_outbox_admin.py` e `scripts/totvs_outbox_admin.py`:

```powershell
python scripts\totvs_outbox_admin.py metricas
python scripts\totvs_outbox_admin.py listar --status ERROR
python scripts\totvs_outbox_admin.py tentativas --id 12
python scripts\totvs_outbox_admin.py reprocessar --id 12
python scripts\totvs_outbox_admin.py worker --once
```

`reprocessar` tem dois caminhos, nenhum deles editando payload silenciosamente:

- item com payload: volta a `PENDING` com a MESMA chave, o MESMO XML e todo o
  histórico de tentativas preservado;
- item bloqueado, que nunca teve payload: o contrato é remontado a partir do
  MESMO fato canônico imutável, agora que o cadastro TOTVS foi configurado.

## 10. Observabilidade

`metricas_outbound_totvs()` devolve contagem por estado, item pendente mais
antigo com idade em segundos, maior número de tentativas em aberto, última
falha e última entrega OK com `InternalId`. Exposto pelo CLI. Nenhum dashboard
novo foi construído.

## 11. Configuração por ambiente

Todas as chaves nascem desligadas e nenhuma lógica consulta o nome do banco. O
mesmo código serve TESTE e o piloto REAL:

```dotenv
GESTOR_TOTVS_OUTBOX_ENABLED=false
GESTOR_TOTVS_OUTBOX_WORKER_ENABLED=false
GESTOR_TOTVS_OUTBOX_WORKER_INTERVAL_SECONDS=15
GESTOR_TOTVS_OUTBOX_BATCH_SIZE=10
GESTOR_TOTVS_OUTBOX_LEASE_SECONDS=120
GESTOR_TOTVS_OUTBOX_MAX_ATTEMPTS=12
GESTOR_TOTVS_OUTBOX_ZERO_START_ENABLED=false
GESTOR_TOTVS_OUTBOX_TERMINAL_ENABLED=true
GESTOR_TOTVS_OUTBOUND_WASTE_CODE_MAP_JSON={}
GESTOR_TOTVS_OUTBOUND_DEFAULT_WASTE_CODE=
GESTOR_TOTVS_OUTBOUND_STOP_REASON_MAP_JSON={}
GESTOR_TOTVS_OUTBOUND_DEFAULT_STOP_REASON_CODE=
```

Códigos confirmados no TESTE na Etapa 5, disponíveis para preencher os mapas:
`WasteCode` `FH`, `FM`, `FP`, `NC`, `RB`, `RP`; `StopReasonCode` (SX5/44)
`0009` a `0028` e `FE`.

## 12. Verificação

- `tests/test_totvs_outbox.py`: **49 testes** — 21 de domínio puro (backoff,
  classificação, planejamento) e 28 de arquitetura real em PostgreSQL, cada um
  em schema isolado, incluindo a garantia transacional (falha de `INSERT` da
  outbox derruba a transição inteira) e a preservação de refugo/parada
  bloqueados;
- `tests/test_migration_chain_11_19.py`: **8 testes** da cadeia de migrations
  que o banco REAL percorrerá;
- suíte completa: **537 testes aprovados, 1 pulado** (o pulo é o mesmo da Etapa
  5: não há fatos na janela histórica de julho/2026 no banco TESTE ativo);
- falha controlada no TOTVS TESTE real: cenários A, B e C aprovados, com
  `InternalId 783166` e rejeição funcional `A680OPTOT` reais.

## 13. Banco REAL e o piloto

O banco REAL `gestor_pecas` está em **schema 11**; a aplicação exige **19**. Em
01/09/2026 o gap foi auditado **somente em leitura** e o caminho 11 → 19 foi
ensaiado fora do REAL, com aprovação. Nada foi executado no REAL. Procedimento,
risco por migration e critérios de abortar em
`docs/PROMOCAO_SCHEMA_REAL_11_19.md`.

Schema preparado não é integração ligada: mesmo depois da promoção,
`GESTOR_TOTVS_OUTBOX_ENABLED` e `GESTOR_TOTVS_OUTBOX_WORKER_ENABLED` continuam
`false` até a decisão do piloto.

## 14. Pendências reais

- Os mapas `WasteCode`/`StopReasonCode` precisam ser preenchidos pela
  Manufatura/PCP antes de ligar `GESTOR_TOTVS_OUTBOX_ENABLED` em operação. Sem
  eles, refugos e paradas ficam registrados como `ERROR` bloqueado, com todos os
  valores preservados, mas não são entregues.
- Promoção do REAL para o schema 19 depende de autorização e janela da TI.
- Reconciliação bidirecional automática continua fora do escopo (Etapa 9).
