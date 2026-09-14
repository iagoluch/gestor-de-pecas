# Hotfix v11 — autenticação e integridade de runtime

> Registro histórico de 19/08/2026. Referências à interface da época não são instruções de execução atuais.

Data: 19/08/2026

## Correção aplicada

A consolidação da v11 moveu normalização e constantes para módulos de `app.core`, mas removeu por engano cinco símbolos ainda utilizados por `app/database/database.py`:

- `PASSWORD_SCHEME`
- `PASSWORD_ITERATIONS`
- `LEGACY_PASSWORD_ITERATIONS`
- `CATALOG_SYNC_LOCK_ID`
- `agora_db()`

Isso causava `NameError` durante a autenticação antes mesmo da validação da senha.

Os símbolos foram restaurados com os mesmos valores/comportamento da v10, preservando compatibilidade com hashes PBKDF2 atuais e hashes legados.

Também foi corrigida uma importação ausente de `OperationVisual` em `tests/test_operator_screen_flow.py`.

## Validação executada

- `python -m compileall -q .`: OK
- análise estática por `symtable` para referências globais indefinidas em todos os `.py`: 0 ocorrências
- 110 testes de backend/domínio executáveis neste ambiente: 110 aprovados
- teste isolado dos helpers de autenticação, incluindo hash atual, senha incorreta, hash legado e rehash: OK
Também foram removidos nomes de arquivo com escapes Unicode literais.

Os testes que exigem PostgreSQL/Psycopg real, PySide6 ou recursos exclusivos do Windows devem ser executados no ambiente Windows do projeto.

## Arquivos locais deliberadamente não incluídos

O pacote não contém segredos ou artefatos específicos da máquina, incluindo `.env`, `.venv`, `.qlik_credentials.bin` e cookies de sessão. Reutilize esses itens do backup local quando aplicável.
