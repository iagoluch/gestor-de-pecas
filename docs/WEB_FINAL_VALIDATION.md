# Validação final da base Web

Este documento descreve o contrato vigente após a consolidação de 24/08/2026.

## Critérios automatizáveis

- importar backend/API sem dependência gráfica;
- compilar os módulos Python;
- executar testes de domínio, serviços, HTTP e frontend;
- construir `web/dist`;
- rejeitar transição HTTP inválida no backend;
- aceitar todos os estados físicos canônicos, incluindo `fila`;
- confirmar que não existem imports, entrypoints ou requisitos da interface
  removida;
- varrer arquivos de texto por corrupção de UTF-8.

## Critérios que exigem ambiente controlado

- migrations e concorrência em `TEST_DATABASE_URL` isolada;
- login e permissões com usuários autorizados;
- leitor/crachá e interação real no posto;
- virada de turno, Corte/Nesting e Destaque em fluxo produtivo controlado;
- observação real de SSE, rede e reverse proxy.

Resultado automatizado não deve ser apresentado como prova de operação real.
