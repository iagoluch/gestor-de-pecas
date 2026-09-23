# Backup do banco TESTE

O backup local do banco oficial `gestor_pecas_test` é gerado por
`scripts/backup_banco_teste.py`. O comando só aceita esse alvo literal, cria um
arquivo PostgreSQL custom (`.dump`), verifica sua estrutura com
`pg_restore --list` e grava um manifesto com SHA-256. Nenhum dado é restaurado
por esse fluxo.

## Execução

Primeiro revise o alvo e o local de saída sem executar Docker:

```powershell
python scripts/backup_banco_teste.py --dry-run --output-dir backups/test
```

Depois, para criar o backup TESTE:

```powershell
python scripts/backup_banco_teste.py --confirmar gestor_pecas_test --output-dir backups/test
```

O script usa o serviço `postgres` do `compose.yaml`; informe
`--docker-service <nome>` apenas se o serviço tiver outro nome. Os artefatos em
`backups/test/` são dados locais e não entram no Git.

## Restauração

Um backup não deve ser restaurado sobre `gestor_pecas_test` em uso. A prova de
recuperação precisa usar banco descartável, com responsável e janela definidos
pela operação. Não há nesta fase agendamento, retenção nem cópia externa: esses
três pontos dependem da política de RPO/DR aprovada e continuam pendentes.
