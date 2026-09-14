# Baseline da migração Web

> Registro histórico de 20/08/2026. Não descreve o runtime vigente; consulte `WEB_ARCHITECTURE.md`.

Data do levantamento: 20/08/2026 (America/Sao_Paulo).

## Fonte auditada

- [Confirmado] O trabalho foi iniciado sobre o workspace `Gestor de Peças - Area de Testes`, que contém a aplicação Python/PySide6 completa e arquivos alterados em 20/08/2026.
- [Não verificado] O arquivo citado na missão, `Gestor de Peças - Area de Testes(20260820-164422).zip`, não estava disponível no computador nem nos anexos. Por isso não foi possível conferir o workspace byte a byte contra esse ZIP.
- [Confirmado] O pacote visual `Gestores.zip` foi validado com SHA-256 `D900C2BF0076647C719C63CDAC7D0FC0B74AE9E55FC56991BDDF62D2F780BF40` e extraído em `assets/screens/Gestores/`.
- [Confirmado] O pacote visual contém 29 mockups gerenciais individuais de 1920 x 1080, uma prancha geral e um guia de referência. Os dados mostrados nos mockups são explicitamente ilustrativos e não serão usados como dados da aplicação.

## Arquitetura encontrada

- Entrypoint desktop: `gestordepeca.py` -> `app.main_window.main()` -> `app.launcher.run_application()`.
- Interface atual: PySide6 em `app/ui/` e `app/ui/main_window_sections/`.
- Persistência: PostgreSQL síncrono com `psycopg`, `psycopg_pool`, migrations versionadas e facade `app.database.Database`.
- Domínio e analytics neutros de interface: `mes/domain/` e `mes/analytics/`.
- Contratos neutros: `mes/contracts/`.
- Casos de uso: `mes/services/`.
- Fronteira preparada para Web: `mes.services.frontend_facade.FrontendBackendFacade`.
- Integração legada Qlik preservada em `qlik/` e nos serviços de catálogo/busca.
- Autenticação atual: tabela PostgreSQL `usuarios`, senha PBKDF2-SHA256 e níveis centralizados em `app/core/permissions.py`.
- [Confirmado] Não foi encontrado frontend Web ou backend HTTP preexistente.
- [Confirmado] `mes/domain`, `mes/analytics`, `mes/contracts` e `mes/services` não importam PySide6 nem FastAPI.
- [Confirmado] A UI desktop ainda possui acessos diretos ao objeto `Database`; a nova Web não repetirá esse acoplamento e consumirá a facade/casos de uso.

## Ambiente de execução

- Python: 3.14.7 em `C:\Python314\python.exe`.
- Node.js: 24.19.0.
- npm: 11.17.0.
- `TEST_DATABASE_URL`: ausente no baseline.
- [Confirmado] O diretório não é um repositório Git ativo, portanto não existe diff/commit de referência para esta cópia.

## Testes antes da migração

Comando executado:

```text
C:\Python314\python.exe -m unittest discover -s tests
```

Resultado: 233 testes executados em 72,058 s; 230 passaram e 3 falharam.

Falhas preexistentes:

1. `test_catalogos_atual_e_legacy_preservam_dimensoes_oficiais`: o diretório esperado `assets/screens/screens - atuais/` não existe nesta cópia e os 24 PNGs do catálogo desktop não foram encontrados.
2. `test_fila_corte_exibe_atualizar_fundo_claro_cards_centrados_e_datas`: nenhum dos 12 labels esperados da fila de Corte foi localizado.
3. `test_operador_corte_tem_acesso_a_fila_automatica_do_setor`: a UI exibe `0/2 concluídos`, enquanto o contrato do teste espera `0/2 nestings concluídos`.

Essas falhas pertencem ao baseline desktop/operador. Não serão mascaradas por alteração de testes e não serão misturadas à implementação gerencial antes do checkpoint obrigatório.

## Limites de validação do baseline

- [Não verificado] Integração com PostgreSQL real, porque não havia `TEST_DATABASE_URL` isolada configurada.
- [Não verificado] Sessão Qlik real e renovação de credenciais.
- [Não verificado] Fluxo produtivo completo conduzido por um operador real.
- [Não verificado] Correspondência do workspace com o ZIP-fonte citado, pois esse arquivo não estava disponível.
