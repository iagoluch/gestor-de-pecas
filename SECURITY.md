# SECURITY.md — Gestor de Peças

Extraído do `AGENTS.md` em 2026-09-29; tem a mesma força normativa do `AGENTS.md`.

## Segurança e consistência transacional

- eventos técnicos não devem poluir histórico produtivo;
- não reescrever evento histórico para esconder inconsistência.

O Quick Tunnel usado em homologação é temporário e não pode virar endpoint de produção.

## Artefatos entregues

- Não incluir `.env`, credenciais Qlik, tokens, perfis de navegador, caches, `.venv`, `__pycache__` ou `.pyc` em artefatos entregues.
