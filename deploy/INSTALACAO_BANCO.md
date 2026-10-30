# Instalação do banco de dados (PostgreSQL 17) na VM

Tutorial só do banco. Parte do zero: PostgreSQL desinstalado, nada de banco antigo.
Ao final você tem o PostgreSQL rodando em `D:\postgresql` com o banco `gestor_pecas` restaurado na versão 68.

Tempo: uns 30 minutos (o instalador demora mais).

Regra de ouro: rode tudo no **PowerShell como Administrador**. Depois do passo 8, qualquer janela nova também precisa ser como Administrador.

---

## Antes de começar

Confirme que existem estes dois arquivos (o caminho pode ter pasta dupla, veja o passo 11):

- `D:\instalacao\gestor-pecas-deploy\gestor_pecas.dump`
- o instalador do PostgreSQL 17 para Windows x64 (EDB)

---

## Parte 1 — Limpar o PostgreSQL antigo

1. Feche o pgAdmin e qualquer janela do `psql`.
2. Abra **Programas e Recursos**, selecione **PostgreSQL 17** e clique em **Desinstalar**. Aceite remover tudo.
3. Apague o que sobrar. Se você já usou `D:\postgresql` antes, apague também (o desinstalador deixa a pasta de dados):
   ```powershell
   Remove-Item "D:\postgresql" -Recurse -Force -ErrorAction SilentlyContinue
   Remove-Item "C:\Program Files\PostgreSQL" -Recurse -Force -ErrorAction SilentlyContinue
   ```
4. Reinicie a VM.

---

## Parte 2 — Instalar o PostgreSQL 17

5. Rode o instalador do PostgreSQL 17 (Windows x64) como Administrador e preencha assim:

   | Tela | O que colocar |
   |---|---|
   | Installation Directory | `D:\postgresql` |
   | Select Components | marque **PostgreSQL Server** e **Command Line Tools**. pgAdmin é opcional. Desmarque Stack Builder |
   | Data Directory | `D:\postgresql\data` (confira, o instalador sugere sozinho) |
   | Password (do `postgres`) | escolha uma senha forte e **anote agora** |
   | Port | `5432` |
   | Locale | o que você já escolheu (`en_US`). Pode ficar assim |

6. Clique em Next até instalar e espere terminar. Não feche a janela.

---

## Parte 3 — Conferir e liberar os comandos

7. Abra um PowerShell **novo**, como Administrador, e confira o serviço:
   ```powershell
   Get-Service postgresql*
   ```
   Esperado: um serviço com `Status = Running` (nome parecido com `postgresql-x64-17`).

8. Grave o PATH da máquina (uma vez só):
   ```powershell
   [Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","Machine") + ";D:\postgresql\bin", "Machine")
   ```
   **Feche** esse PowerShell e **abra outro**, também como Administrador.

9. Confira que os comandos existem:
   ```powershell
   psql --version
   pg_restore --version
   ```
   Esperado: `psql (PostgreSQL) 17.x` e `pg_restore (PostgreSQL) 17.x`.

10. Teste o login do `postgres` (use a senha do passo 5):
    ```powershell
    $env:PGPASSWORD = "<senha do postgres>"
    psql -h 127.0.0.1 -U postgres -d postgres -c "select version();"
    ```
    Esperado: uma linha começando com `PostgreSQL 17`.

---

## Parte 4 — Criar o usuário e o banco

11. Defina a pasta do pacote. **Confira** que o dump está lá:
    ```powershell
    $P = "D:\instalacao\gestor-pecas-deploy"
    Test-Path "$P\gestor_pecas.dump"
    ```
    Esperado: `True`.
    Se vier `False`, a pasta está duplicada. Rode `dir D:\instalacao`, entre na pasta de dentro e ajuste o `$P` (exemplo: `D:\instalacao\gestor-pecas-deploy\gestor-pecas-deploy`). Repita o `Test-Path` até dar `True`.

12. Crie a senha do usuário do sistema (`gestor_app`) e guarde em arquivo:
    ```powershell
    $b = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    $senhaApp = ($b | ForEach-Object { $_.ToString('x2') }) -join ''
    Set-Content "D:\instalacao\senha-gestor_app.txt" $senhaApp -Encoding ASCII
    ```
    Essa senha vai para o `.env` na Parte E do roteiro principal. O arquivo é apagado no fim, junto com a pasta `D:\instalacao`.

13. Crie o usuário e o banco (use a senha do `postgres` no `PGPASSWORD`):
    ```powershell
    $env:PGPASSWORD = "<senha do postgres>"
    "CREATE ROLE gestor_app LOGIN PASSWORD '$senhaApp';`nCREATE DATABASE gestor_pecas OWNER gestor_app ENCODING 'UTF8' TEMPLATE template0;" | psql -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1
    ```
    Esperado: `CREATE ROLE` e `CREATE DATABASE`.
    Não use `LOCALE` nesse comando. O banco herda o padrão da instalação e isso é o certo.

---

## Parte 5 — Restaurar os dados

14. Restaure o dump (leva alguns minutos e **não mostra nada** se der certo):
    ```powershell
    $env:PGPASSWORD = $senhaApp
    pg_restore -h 127.0.0.1 -U gestor_app -d gestor_pecas --no-owner --no-acl --exit-on-error "$P\gestor_pecas.dump"
    ```
    Voltou ao prompt sem erro = deu certo.

15. Confira a versão do banco:
    ```powershell
    psql -h 127.0.0.1 -U gestor_app -d gestor_pecas -c "select max(version) from schema_migrations;"
    ```
    Esperado: **68**.

16. Confira que há tabelas:
    ```powershell
    psql -h 127.0.0.1 -U gestor_app -d gestor_pecas -c "select count(*) from information_schema.tables where table_schema='public';"
    ```
    Esperado: um número maior que zero (dezenas de tabelas).

17. Limpe a senha da sessão:
    ```powershell
    Remove-Item Env:PGPASSWORD
    ```

Pronto: banco no ar. Volte ao roteiro principal (`INSTALACAO_MANUAL.md`) na parte do `.env` (Parte E), usando a senha do arquivo `D:\instalacao\senha-gestor_app.txt` e o caminho `D:\gestor-pecas`.

---

## Se algo der errado

| Sintoma | O que fazer |
|---|---|
| `pg_restore não é reconhecido` | Você não abriu um PowerShell novo depois do passo 8. Feche e abra outro. Teste rápido: `$env:Path += ";D:\postgresql\bin"` |
| `password authentication failed for user "postgres"` | Senha do `postgres` errada. Use a do passo 5 |
| `role "gestor_app" already exists` | Sobrou lixo de tentativa anterior. Rode o reset abaixo e refaça do passo 13 |
| `database "gestor_pecas" already exists` | Idem: rode o reset abaixo e refaça do passo 13 |
| `pg_restore` deu erro no meio | O banco ficou pela metade. Rode o reset abaixo, refaça os passos 13 e 14 e me mande a mensagem do erro |
| `select max(version)` não dá 68 | Pare e me mande o número que apareceu |

**Reset do banco** (apaga só o `gestor_pecas` e o usuário `gestor_app`; o dump continua na pasta):
```powershell
$env:PGPASSWORD = "<senha do postgres>"
"DROP DATABASE IF EXISTS gestor_pecas;`nDROP ROLE IF EXISTS gestor_app;" | psql -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1
```
Depois volte ao passo 12 (nova senha) e siga.

---

## Lembretes para depois

- Na tarefa de backup (roteiro principal, Parte J), o `-PgBin` é `D:\postgresql\bin`.
- O banco é só para esta VM. Não crie regra de firewall para a porta 5432 e não mexa no `pg_hba.conf`.
- A senha do `postgres` (passo 5) vai para o cofre de senhas. Ela serve para manutenção e para o backup.
