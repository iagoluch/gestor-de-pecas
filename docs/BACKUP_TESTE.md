# Backup do banco TESTE — runbook para a infraestrutura

`scripts/backup_banco_teste.py` é a **capacidade** de backup e restauração que o
aplicativo oferece para o banco oficial `gestor_pecas_test`. A **operação**
(quando rodar, por quanto tempo guardar, para onde copiar, quem monitora) é
responsabilidade da infraestrutura e está descrita na seção "Responsabilidades".

O script faz:

- `pg_dump` em formato custom (`.dump`), dentro do container do compose, só do
  banco `gestor_pecas_test` e somente com a confirmação literal do nome;
- validação estrutural com `pg_restore --list` antes de publicar o arquivo;
- manifesto `<arquivo>.dump.json` com banco, tamanho em bytes e SHA-256;
- gravação atômica: o arquivo e o manifesto só aparecem com o nome final depois
  da validação; em falha, os `.partial` são removidos;
- verificação posterior (`--verificar`) contra o manifesto;
- restauração (`--restaurar`) somente em banco descartável `gestor_restore_*`,
  já criado e vazio, com confirmação literal do alvo.

O script **não** agenda execução, **não** apaga backups antigos e **não** copia
dados para fora da máquina.

## Pré-requisitos

- Rodar na raiz do repositório, com o `compose.yaml` e o serviço `postgres` no ar
  (use `--docker-service <nome>` se o serviço tiver outro nome).
- `TEST_DATABASE_URL` apontando para `gestor_pecas_test`. Se
  `GESTOR_EXPECTED_DATABASE` estiver definida, ela precisa valer
  `gestor_pecas_test`, senão o script recusa (exit 2).
- Os artefatos ficam em `backups/test/`, que não entra no Git.

## Comandos

1. Revisar o plano sem executar Docker nem criar arquivos:

   ```powershell
   python scripts/backup_banco_teste.py --dry-run --output-dir backups/test
   ```

2. Gerar o backup:

   ```powershell
   python scripts/backup_banco_teste.py --confirmar gestor_pecas_test --output-dir backups/test
   ```

   Saída em stdout: o manifesto em JSON. Arquivos gerados:
   `backups/test/gestor_pecas_test_<AAAAMMDDTHHMMSSZ>_<id>.dump` e o `.dump.json`.

3. Verificar um backup existente (por exemplo, depois de copiá-lo para outro
   lugar e trazê-lo de volta):

   ```powershell
   python scripts/backup_banco_teste.py --verificar backups/test/<arquivo>.dump
   ```

   Confere o manifesto ao lado do arquivo, o tamanho, o SHA-256 e
   `pg_restore --list`. **Copie sempre o `.dump` junto com o `.dump.json`.**

4. Ensaio de restauração em banco descartável:

   ```powershell
   docker compose exec -T postgres createdb -U <usuario> gestor_restore_20260923
   python scripts/backup_banco_teste.py --restaurar backups/test/<arquivo>.dump `
       --alvo gestor_restore_20260923 --confirmar-alvo gestor_restore_20260923
   # conferir o banco restaurado (contagens, login de teste etc.)
   docker compose exec -T postgres dropdb -U <usuario> gestor_restore_20260923
   ```

   Proteções da restauração:

   - o alvo precisa começar com `gestor_restore_` e conter só `[a-z0-9_]`;
   - `--confirmar-alvo` precisa repetir `--alvo` literalmente;
   - `gestor_pecas`, `gestor_pecas_test`, `postgres`, `template0`, `template1` e
     os bancos de `DATABASE_URL`/`TEST_DATABASE_URL` são sempre recusados;
   - o backup é verificado (manifesto + SHA-256 + `pg_restore --list`) antes de
     qualquer escrita;
   - o alvo precisa existir e estar vazio (sem tabelas de usuário);
   - `pg_restore` roda com `--single-transaction --exit-on-error`: ou restaura
     tudo, ou nada.

   Restaurar sobre o banco TESTE em uso ou sobre o REAL **não é suportado** pelo
   script. Promover um banco restaurado é uma decisão operacional manual.

## Códigos de saída e log

| Código | Significado | Ação sugerida |
|---|---|---|
| 0 | sucesso | nenhuma |
| 1 | falha de execução (Docker, `pg_dump`, `pg_restore`, disco) | alertar; tentar de novo na próxima janela |
| 2 | uso inválido ou alvo recusado (nada foi executado) | corrigir o comando/configuração |
| 3 | integridade: manifesto ausente/divergente, SHA-256 ou estrutura inválida | alertar; o arquivo não serve para restauração |

Cada etapa escreve uma linha JSON em **stderr** com `ts` (UTC) e `event`:
`backup_started`, `backup_ok`, `verify_started`, `verify_ok`, `restore_started`,
`restore_ok`, `refused`, `integrity_failed`, `failed` (os três últimos com
`reason`). O stdout fica reservado ao resultado em JSON. Erros de argumento do
`argparse` também saem com código 2.

## Responsabilidades da infraestrutura

Ficam fora do aplicativo, por decisão registrada em `docs/STATUS_ATUAL.md`
(item F21):

- **Agendamento:** rodar o comando 2 a cada **8 horas** (agendador do host da
  VM ou equivalente), seguido do comando 3 sobre o arquivo gerado.
- **Retenção:** manter **21 backups (7 dias)** e apagar os mais antigos, sempre
  o `.dump` junto com o `.dump.json`.
- **Cópia fora da VM:** replicar os pares `.dump` + `.dump.json` para um
  armazenamento fora da máquina e validar a cópia com `--verificar`.
- **Monitoramento:** alertar em qualquer código de saída diferente de 0 ou na
  falta de um `backup_ok` dentro da janela esperada.
- **Controle de acesso:** o diretório de backup e a cópia externa contêm dados
  de produção de teste; restrinja leitura a quem opera o banco.
- **Ensaio de restauração:** executar o comando 4 periodicamente e registrar o
  resultado.
- **RPO/RTO:** definir e aprovar. Com backups a cada 8 h, o RPO máximo é de
  8 h; o RTO depende do tamanho do banco e deve ser medido no ensaio.
