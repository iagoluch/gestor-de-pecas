# Arquitetura Web consolidada

Desde 24/08/2026, a Web é a única interface operacional do Gestor de Peças.

```text
React / TypeScript
        ↓ HTTP + SSE
FastAPI
        ↓
contracts/services
        ↓
domain/analytics
        ↓
repository PostgreSQL
```

## Fronteiras

- `web/` contém apenas apresentação, interação e estado visual;
- `backend/api/` adapta autenticação, autorização e casos de uso para HTTP;
- `mes/domain/operator_state_machine.py` é a fonte canônica das transições;
- `mes/services/` valida e orquestra a regra industrial;
- `app/database/` garante atomicidade, concorrência e persistência;
- `eventos_estado_recurso` é a fonte canônica de estado físico;
- fatos de quantidade, execução, tempo e rateio permanecem separados.

O frontend pode antecipar estados de UX, mas a API rejeita qualquer comando que
viole domínio, roteiro, autorização, quantidade ou estado do recurso.

## Estado e retomada

Parada e Setup preservam `estado_retorno` quando interrompem Produção ou
Retrabalho. Assim, retomadas não convertem Retrabalho em Produção. A transição
direta de Retrabalho para Produção é proibida. A migration v13 adiciona as
colunas com valor inicial nulo e não preenche registros históricos.

## Integrações

O PostgreSQL continua sendo a persistência técnica atual. A porta corporativa
permanece fechada até a TI definir o contrato Protheus/TOTVS. Qlik é legado
bloqueado e não recebe regra de negócio nova.
