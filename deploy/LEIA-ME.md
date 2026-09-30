# Primeira instalação do Gestor de Peças na VM

Roteiro do fluxo inteiro:

1. instalação do zero (Windows Server + PostgreSQL 17 nativo + nginx + NSSM), §1–5;
2. runner do GitHub Actions, §6;
3. deploys seguintes por tag `v*` (`.github/workflows/deploy.yml`), §7;
4. o que ainda depende de informação externa, §8.

## 1. Montar o pacote (no notebook)

```bash
python deploy/montar_pacote.py
```

O script gera `dev_reports/deploy_vm/gestor-pecas-deploy.zip` com:

- o código do HEAD;
- o `web/dist` recém-construído;
- o dump atual do REAL;
- o `.env` deste notebook sem as chaves que variam de máquina para máquina;
- o certificado autoassinado.

**O zip carrega segredos e dados de produção.** Copie-o só por meio
controlado (pasta compartilhada da VM ou pendrive) e nunca o versione.

Ensaio em VirtualBox no próprio notebook: a pasta compartilhada só aparece
depois de reiniciar a VM com os Adicionais instalados, e o NAT do VirtualBox 7
não alcança o `localhost` do notebook (`10.0.2.2` não responde). O caminho que
funciona sem reiniciar é servir a pasta pela interface host-only, que só existe
dentro do notebook:

```bash
python -m http.server 8765 --bind 192.168.56.1 --directory dev_reports/deploy_vm
```

Na VM: `curl.exe -fLo C:\instalacao\pacote.zip http://192.168.56.1:8765/gestor-pecas-deploy.zip`.
Pare o servidor logo depois do download.

## 2. Antes de instalar: o que é compartilhado com o notebook

O `.env` vem do notebook, então a VM usa os **mesmos** Telegram, TOTVS e SigmaNEST:

- **Telegram:** o instalador grava `TELEGRAM_ENABLED`, `GESTOR_TELEGRAM_BOT_POLLING_ENABLED` e `GESTOR_TELEGRAM_DIGEST_ENABLED` como `false`. O mesmo bot em dois lugares briga pelo polling e duplica o digest nos chats reais. Para testar o bot na VM:
  1. pare o app do notebook;
  2. troque as três chaves para `true` em `C:\gestor-pecas\.env`;
  3. rode `Restart-Service gestor-pecas`.
- **SOAP de entrada do TOTVS:** continua apontado para o túnel do notebook. Na VM, o receptor fica indisponível até existir `GESTOR_TOTVS_SOAP_ALLOWED_SOURCE_CIDRS` com o IP do Protheus. O pull de OP sob demanda funciona.
- **Outbox para o TOTVS:** segue o `.env`; hoje está desligada.

## 3. Preparar a VM

1. Instale o Windows Server 2025. A [versão de avaliação](https://www.microsoft.com/evalcenter/evaluate-windows-server-2025) serve para o ensaio.
   - Recomendado: 8 vCPU, 16 GB, 200 GB.
   - Rede: uma que alcance a internet (Protheus cloud) e a rede da fábrica (SigmaNEST `192.168.0.218`).
2. Ajuste o fuso para Brasília: `Set-TimeZone -Id 'E. South America Standard Time'`. O instalador para se o fuso estiver errado.
   - Confira também a **hora**: apontamento e OEE dependem dela. No ensaio, o relógio da VM atrasou ~8 min durante a instalação do PostgreSQL e só voltou quando o `VBoxService` ressincronizou. Em VM, deixe a sincronização do hipervisor ou o `w32time` ativos (`w32tm /query /status`) e compare com um relógio confiável antes de liberar para a fábrica.
3. Instale os pré-requisitos. Caminho automático, depois de extrair o zip (seção 4), num PowerShell como Administrador:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   C:\instalacao\gestor-pecas-deploy\app\deploy\instalar_prerequisitos.ps1
   ```

   O script baixa e instala tudo da tabela abaixo sem perguntas e aceita as licenças do ODBC da Microsoft e do instalador EDB. Ele gera a senha do `postgres` em `C:\instalacao\gestor-pecas-deploy\postgres-senha.txt` (só Administradores), que o `instalar_vm.ps1` usa sem perguntar. O PostgreSQL leva uns 20 min numa VM de 2 vCPU/3 GB. Abra um PowerShell novo depois, para pegar o PATH atualizado.

   Caminho manual, componente por componente:

| Componente | Onde | Observação |
| --- | --- | --- |
| Python 3.14 | [python.org](https://www.python.org/downloads/windows/) | instalador *Windows installer (64-bit)*, com **Install for all users** e o launcher `py`; o instalador recusa Python dentro de `C:\Users` |
| PostgreSQL 17 | [EDB](https://www.enterprisedb.com/downloads/postgres-postgresql-downloads) | anote a senha do usuário `postgres`; porta 5432 |
| nginx para Windows | [nginx.org](https://nginx.org/en/download.html) (versão *stable*) | extrair em `C:\nginx` |
| NSSM | [nssm.cc](https://nssm.cc/download) | `nssm.exe` (win64) numa pasta do PATH |
| ODBC Driver 18 for SQL Server | [Microsoft](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) | SigmaNEST |
| PowerShell 7 | [Microsoft](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows) | exigido pelo `deploy.yml` (`shell: pwsh`) |

## 4. Instalar

Extraia o zip, por exemplo em `C:\instalacao`. Depois, num PowerShell **como Administrador**:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
C:\instalacao\gestor-pecas-deploy\app\deploy\instalar_vm.ps1
```

A única pergunta é a senha do `postgres`. Ela é pulada quando o `instalar_prerequisitos.ps1` gerou o `postgres-senha.txt`, e também na reexecução, quando o `.env` já conecta no banco. O script executa, nesta ordem:

1. confere os pré-requisitos;
2. copia o código para `C:\gestor-pecas`, sem `docs/`, `tests/` e as pastas de ferramentas de desenvolvimento (`.claude`, `.github` etc.), e restringe a pasta a Administradores e SYSTEM;
3. cria o role `gestor_app` com uma senha nova e restaura o dump no banco `gestor_pecas`;
4. gera o `.env` com segredos novos e os hosts da VM;
5. recria a `.venv` do zero com as dependências do `requirements.lock` do pacote;
6. configura o nginx com HTTPS, com o `nginx.conf` do pacote;
7. registra os serviços `gestor-pecas` e `nginx`, cada um na sua conta virtual (sem senha):
   - `NT SERVICE\gestor-pecas` lê o código e o `.env` e só escreve em `dados\` e `dev_reports\`;
   - `NT SERVICE\nginx` lê `C:\nginx` e a chave TLS e só escreve em `logs\` e `temp\`;
   - `C:\nginx` e a pasta do `nssm.exe` perdem a herança da raiz de `C:\`, onde qualquer usuário cria arquivos;
   - as duas contas ficam só com `SeChangeNotifyPrivilege` e `SeCreateGlobalPrivilege` (`sc privs`); confira com `sc.exe qprivs nginx`;
8. libera as portas 80/443 no firewall;
9. valida `/api/v1/system/ready` direto no Uvicorn e através do nginx.

Pode rodar de novo sem risco:

- banco e `.env` já existentes são mantidos;
- se o restore falhar, o banco incompleto é apagado;
- para restaurar um dump mais novo, rode `DROP DATABASE gestor_pecas` como `postgres` e execute de novo. A senha do `.env` é reaproveitada;
- na reexecução, o nssm imprime `Invalid account name!` antes de cada `Set parameter`: ele não reconhece conta virtual, mas grava o parâmetro. É só aviso.

Regra para quem administra a VM: **nada de `C:\gestor-pecas` roda como Administrador**. O runner (§6) escreve lá, então um script, `pip` ou `.venv` dessa pasta pode ter sido trocado. Por isso o instalador lê o lock e o `nginx.conf` do pacote e recria a `.venv`.

Depois do sucesso e do runner (§6), **apague `C:\instalacao`**: o dump do REAL e a chave do certificado ficam lá sem restrição de acesso. Antes, guarde num cofre a senha do `postgres` (`postgres-senha.txt`, se veio do script): ela é necessária para `DROP DATABASE` e manutenção.

## 5. Acessar

- Na própria VM: <https://localhost>.
- De outra máquina: adicione `<IP da VM>  gestor-peca` em `C:\Windows\System32\drivers\etc\hosts` e abra <https://gestor-peca>.
- O certificado é autoassinado, então o navegador vai avisar. Para parar o aviso, importe `certs\gestor-pecas.crt` em *Autoridades de Certificação Raiz Confiáveis* da máquina cliente.
- Pelo IP também abre, mas sempre com aviso de certificado (o IP da VM não está no certificado). Isso só vale se o IP for o mesmo da instalação: ele entra na lista de hosts aceitos. Se o DHCP trocar o IP, ajuste `GESTOR_WEB_ALLOWED_HOSTS`/`ORIGINS` no `.env` e rode `Restart-Service gestor-pecas`.
- Ensaio em VirtualBox com rede NAT: crie os redirecionamentos de porta 443→443 e 80→80 (Configurações → Rede → Avançado → Redirecionamento de Portas, IP do hospedeiro `127.0.0.1`) e abra <https://localhost> no notebook. O `.env` já aceita `localhost` e o IP de NAT da VM (`10.0.2.15`), que entra na lista de hosts por ser o IP dela na instalação.
- Os logins são os mesmos do REAL, porque o banco é o REAL restaurado.

Diagnóstico:

- log do app: `C:\gestor-pecas\dados\logs\gestor-pecas.log`;
- log do nginx: `C:\nginx\logs\error.log`;
- estado dos serviços: `Get-Service gestor-pecas, nginx`.

## 6. Runner do GitHub Actions (uma vez, depois da §4)

O deploy roda num runner self-hosted instalado na própria VM. Ele busca o job no GitHub de dentro para fora, então a VM não precisa de porta de entrada.

1. No notebook, gere o token de registro. Ele vale 1 h e registra quantos runners quiser nesse prazo: não o cole em chat nem o guarde. O comando abaixo imprime o token; redirecione para um arquivo e apague depois:
   `gh api -X POST repos/iagoluch/gestor-de-pecas/actions/runners/registration-token --jq .token`.
   Outra forma: *Settings → Actions → Runners → New self-hosted runner*.
2. Na VM, num PowerShell **como Administrador** aberto depois da §4 (PATH com `pg_dump`):

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   C:\instalacao\gestor-pecas-deploy\app\deploy\instalar_runner.ps1
   ```

   O script pede o token sem ecoar. Também aceita `-Token`.
3. Confira em *Settings → Actions → Runners*: runner `gestor-pecas-vm` com status **Idle**.

O que o `instalar_runner.ps1` faz:

- baixa o runner oficial e confere o SHA-256;
- registra o runner com o label `gestor-pecas-vm`, como serviço;
- troca a conta do serviço para a conta virtual `NT SERVICE\actions.runner.*`;
- dá a essa conta só o que o `deploy.yml` usa:
  - escrita em `C:\gestor-pecas` e em `C:\gestor-pecas.previous` (snapshot do rollback). Isso inclui ler o `.env`, porque o backup pré-deploy tira a `DATABASE_URL` de lá;
  - escrita **só no arquivo** `C:\nginx\conf\nginx.conf`. Como o nginx roda em conta virtual, um conf adulterado alcança só o que o nginx lê, inclusive a chave TLS. Risco aceito: essa conta já lê o `.env`;
  - parar, iniciar e consultar os serviços `gestor-pecas` e `nginx` (sem apagar nem mudar a permissão deles);
- `C:\actions-runner` perde a herança da raiz de `C:\`.

Reexecutar é seguro. Se o `instalar_vm.ps1` rodar de novo, rode este também: ele reaplica as permissões.

**Repositório público + runner self-hosted.** O GitHub desaconselha runner self-hosted em repositório público, porque um PR de fork pode trocar o workflow e rodar código na VM. Mitigações em vigor desde 30/09/2026:

- *Settings → Actions → Fork pull request workflows*: **Require approval for all external contributors**. Nenhum workflow de fora roda sem aprovação.
  - Nunca aprove um PR externo que mexa em `.github/workflows/` sem ler o diff.
- Só o `deploy.yml` pede o label `gestor-pecas-vm`, e ele só dispara por tag, que exige permissão de escrita no repositório.
- A conta do runner não é administradora, app e nginx rodam em contas virtuais, e as três ficam sem `SeImpersonatePrivilege` (`sc privs`, que tira o atalho dos exploits "potato"), então ela não tem caminho para SYSTEM. Conferir: `whoami /priv` num passo do job não lista esse privilégio. Ela alcança o código, o `.env` (e com ele o banco) e a chave TLS. É por isso que a aprovação acima importa.

O repositório ficou privado por algumas horas em 30/09/2026 e voltou a público: a cota de Actions da conta para repositórios privados estava esgotada, e com isso o CI parava.

## 7. Deploy do dia a dia (tag `v*`)

```bash
git tag v1.2.0
git push origin v1.2.0
```

O `.github/workflows/deploy.yml` executa:

1. `validate`: o CI inteiro (backend, frontend, segurança) no commit da tag, em runner do GitHub;
2. `build-frontend`: `npm ci && npm run build`, publicado como artefato `web-dist`;
3. `deploy`, no runner da VM, via `scripts/deploy_release.ps1`:
   1. snapshot de `C:\gestor-pecas` (com `.venv`) em `C:\gestor-pecas.previous`;
   2. `pg_dump` em `C:\gestor-pecas\backups\pre-deploy-<tag>-<data>.dump`. Sem dump, não há deploy;
   3. para o serviço, espelha o código (sem `docs/`, `tests/` e pastas de ferramentas; `.env`, `dados\`, `dev_reports\` e `backups\` ficam intactos), instala o `requirements.lock` com hashes e sobe o serviço;
   4. espera `/ready` por 60 s. Se não ficar pronto, volta código e `.venv` do snapshot;
4. se `deploy/nginx.conf` mudou, grava por cima do atual, reinicia o nginx e confere `/ready` pelo HTTPS. Se falhar, devolve o arquivo anterior e o job falha.

**Rollback.**

- **Código:** automático, como descrito acima.
- **Banco:** nunca volta sozinho. Restaurar o dump apaga os apontamentos feitos depois dele, então isso é decisão de uma pessoa. Quando o código antigo recusa o schema novo, o job falha com o caminho do dump. Nesse caso:

  ```powershell
  Stop-Service gestor-pecas
  pg_restore --clean --if-exists --no-owner --dbname "<DATABASE_URL do .env>" "<dump>"
  Start-Service gestor-pecas
  ```

- **Voltar para uma versão anterior de propósito:** crie uma tag nova apontando para o commit bom. Não mova tag existente.

Diagnóstico de um deploy:

- log do job: aba *Actions* do repositório;
- log do runner na VM: `C:\actions-runner\_diag\`;
- estado: `Get-Service gestor-pecas, nginx, actions.runner.*`.

## 8. Pendências que dependem de informação externa

- **Certificado:** o atual é autoassinado. Troque pelo corporativo, mantendo os nomes de arquivo em `C:\nginx\conf\certs`, e rode `Restart-Service nginx`.
- **`GESTOR_TOTVS_SOAP_ALLOWED_SOURCE_CIDRS`:** falta o IP de saída do Protheus. Sem ele, o receptor SOAP recusa tudo.
- **`GESTOR_OPERATOR_DRAWING_ROOTS`:** falta o caminho de rede real dos desenhos. A conta virtual do app acessa a rede como a conta de computador da VM (`DOMINIO\VM$`):
  - se o compartilhamento aceitar essa conta, basta dar leitura a ela;
  - se exigir um usuário, troque a conta do serviço por uma conta de domínio dedicada: `nssm set gestor-pecas ObjectName DOMINIO\conta senha`, com as mesmas permissões do §4.
- **Telegram:** nasce desligado (§2). Ligue só depois de desligar o bot do notebook.
