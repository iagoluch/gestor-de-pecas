# Relatório de validação — backend consolidado v11 / frontend-ready

> Registro histórico de 19/08/2026. Não descreve o runtime vigente; consulte `WEB_FINAL_VALIDATION.md`.

Data de trabalho: 2026-08-19.

## Compilação

Executado:

```text
python -m compileall -q app mes qlik scripts tests
```

Resultado: **aprovado**.

## Testes executáveis neste ambiente

Foram executados **112 testes**, todos aprovados, cobrindo:

- regras canônicas da Manufatura;
- fim de turno 17:30/21:30;
- fluxo do operador;
- Corte/Nesting;
- produção;
- busca de tarefas;
- estado físico canônico;
- calendário e intervalos;
- analytics industriais;
- simultaneidade e consolidação física;
- rateio;
- auditoria;
- Management View/facade;
- relatórios/Tempo MES;
- permissões;
- runtime;
- sincronização de catálogo;
- resiliência Qlik testável sem conexão real.

A suíte específica `tests/test_backend_canonical_v11.py` possui 11 testes e está incluída nesse total.

## Testes não declarados como aprovados neste container

Alguns módulos da suíte completa exigem dependências/plataforma que não estão instaladas neste ambiente Linux:

- `psycopg` para PostgreSQL e configuração `conninfo`;
- PySide6 para testes Qt/UI;
- `requests_ntlm` para partes da autenticação Qlik;
- DPAPI/Windows para armazenamento seguro de credenciais Qlik.

Esses casos não foram mascarados com stubs e não são contabilizados como sucesso.

## Validação PostgreSQL necessária no Windows/base isolada

Antes de aplicar a v11 em ambiente operacional:

1. usar backup/base isolada;
2. configurar `TEST_DATABASE_URL` para PostgreSQL de teste;
3. abrir a aplicação e confirmar migration até schema 11;
4. validar estado físico do recurso em Início/Parada/Retomada/Setup/Retrabalho;
5. validar Corte/Nesting alterando a timeline física;
6. validar interrupções automáticas de 17:30 e 21:30;
7. validar idempotência ao reabrir a aplicação depois de um limite de turno;
8. validar simultaneidade de OPs e rateio;
9. validar intervalos/exceções de calendário;
10. executar `python -m unittest discover -s tests -v` no ambiente Windows completo.

## Encoding e empacotamento

A entrega final deve:

- permanecer UTF-8;
- preservar acentos em nomes e conteúdo;
- não conter nomes com escapes Unicode indevidos ou texto corrompido;
- excluir `.env`, credenciais, `.venv`, caches e bytecode.
