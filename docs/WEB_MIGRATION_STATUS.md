# Status da migração Web

## Estado atual — 24/08/2026

- Web é a única interface do projeto;
- entrypoints, dependência, testes e ferramentas exclusivos da interface antiga
  foram removidos;
- React continua com o design aprovado, sem redesign nesta etapa;
- a API consome serviços de backend e rejeita transições inválidas;
- a máquina de estados foi movida para `mes/domain/operator_state_machine.py`;
- `fila` foi alinhada à enumeração canônica na validação do repositório;
- o caminho legado que finalizava automaticamente toda a quantidade como boa
  foi eliminado;
- não existe endpoint genérico de edição/exclusão de eventos produtivos;
- a integração Protheus/TOTVS permanece pendente de definição da TI.

Validação automatizada e pendências externas são registradas no relatório de
consolidação desta etapa.
