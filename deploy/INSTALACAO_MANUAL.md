# Gestor de Peças — instalação manual na VM (versão 2)

Roteiro para instalar à mão o que o `instalar.ps1` faz sozinho. Cada passo diz o que fazer, o comando exato e o resultado esperado.
Refeito para esta VM: **Windows Server 2016** (Build 14393), **código em `D:\gestor-pecas`**, **PostgreSQL em `D:\postgresql`**, **pacote em `D:\instalacao`**.
Escrito a partir da leitura dos scripts da pasta `deploy/`. Não foi testado numa VM limpa.

## Onde estamos

| Etapa | Situação |
|---|---|
| PostgreSQL 17 instalado em `D:\postgresql` | feito |
| Banco `gestor_pecas` restaurado, versão 68 | feito (tutorial `INSTALACAO_BANCO.md`) |
| Código copiado para `D:\gestor-pecas` e pastas `dados\logs`, `backups`, `dev_reports` | feito |
| Python, nginx, NSSM, ODBC | **próximo: Parte B** |
| `.env`, ambiente Python, nginx, serviços, backup | a fazer |

Quem ainda não fez algum item "feito" acima: volte ao passo correspondente. Os passos de conferir são seguros de repetir.

## Regras do roteiro

- Todo comando roda no **PowerShell como Administrador**, dentro da VM.
- Cada janela nova do PowerShell **esquece** as variáveis (`$P`, `$senhaApp`). Os blocos abaixo definem de novo o que precisam.
- `$P` = pasta do pacote: `D:\instalacao\gestor-pecas-deploy`. Se existir uma pasta duplicada por dentro (`...\gestor-pecas-deploy\gestor-pecas-deploy`), use a de dentro.
- Onde aparecer `<...>`, troque pelo valor real.
- Se um passo falhar, **pare** e corrija. Não pule.
- Esta VM é **Windows Server 2016**, e os scripts foram escritos para o 2025. Por isso há conferências extras (Python e `curl.exe`). Se algo falhar por incompatibilidade, pare e me avise.

Tempo estimado do que falta: 1 a 1h30.

---

## Parte A — Preparação (conferir)

### Passo 1 — Pacote no lugar
```powershell
$P = "D:\instalacao\gestor-pecas-deploy"
Test-Path "$P\gestor_pecas.dump", "$P\gestor.env.base", "$P\certs", "$P\app\requirements.lock"
```
Esperado: quatro `True`.

### Passo 2 — Fuso de Brasília (turnos e OEE dependem disso)
```powershell
Set-TimeZone -Id "E. South America Standard Time"
(Get-TimeZone).Id
```
Esperado: `E. South America Standard Time`. Compare a hora com um relógio confiável (`w32tm /query /status`).

### Passo 3 — Telegram do notebook desligado
Peça a quem usa o notebook para desligar. A VM usa o mesmo bot: com os dois ligados, o bot responde duplicado.

### Passo 4 — Parar de apontar produção no notebook
O banco da VM é uma foto do dia em que o zip foi montado (28/10, 15:04). O que for apontado no notebook depois disso **não chega** à VM. Antes de a fábrica usar a VM, decida a data da virada.

---

## Parte B — Instalar os programas

PostgreSQL já está instalado. Faltam quatro. Se algum já estiver instalado, só rode a conferência.

### Passo 5 — Python 3.14 (python.org)
Na primeira tela do instalador marque:
- **Install for all users**
- **Add python.exe to PATH**
- **py launcher**

Instalar só para o usuário **não funciona**: o serviço do Windows não lê o perfil do administrador.

Abra um PowerShell novo como Administrador e confira:
```powershell
py -3.14 --version
py -3.14 -c "import sys; print(sys.base_prefix)"
```
Esperado: `Python 3.14.x` e um caminho que **não** comece com `C:\Users\`.
Se o instalador não abrir ou o `py -3.14` não funcionar, o Python 3.14 pode não suportar o Windows Server 2016. **Pare e me avise.** Não instale outra versão.

### Passo 6 — nginx para Windows (nginx.org, 1.30.x, zip)
Extraia de modo que exista `C:\nginx\nginx.exe`. A pasta deve se chamar exatamente `C:\nginx`, sem número de versão.
```powershell
Test-Path C:\nginx\nginx.exe
```
Esperado: `True`.

### Passo 7 — NSSM 2.24 (nssm.cc)
O NSSM é o programa que transforma o sistema em serviço do Windows (sobe sozinho e reinicia se cair).
Copie `win64\nssm.exe` para `C:\tools\nssm\nssm.exe` e coloque a pasta no PATH:
```powershell
$p = [Environment]::GetEnvironmentVariable("Path","Machine")
if (($p -split ";") -notcontains "C:\tools\nssm") { [Environment]::SetEnvironmentVariable("Path","$p;C:\tools\nssm","Machine") }
```

### Passo 8 — Microsoft ODBC Driver 18 for SQL Server
Instale pelo instalador da Microsoft (aceite a licença). É usado para ler o banco do SigmaNEST.

### Passo 9 — PATH e conferência geral
**Feche o PowerShell e abra outro como Administrador** (para o PATH novo valer). Rode:
```powershell
nssm version
psql --version
py -3.14 --version
Get-OdbcDriver -Name "ODBC Driver 18 for SQL Server"
```
Esperado: os quatro respondem. O `psql` deve responder porque o PATH do PostgreSQL (`D:\postgresql\bin`) foi gravado antes.

---

## Parte C — Código e pastas

### Passo 10 — Conferir o código copiado
```powershell
Test-Path D:\gestor-pecas\requirements.lock, D:\gestor-pecas\backend, D:\gestor-pecas\web\dist, D:\gestor-pecas\dados\logs, D:\gestor-pecas\backups
```
Esperado: cinco `True`. Se faltar algo, refaça:
```powershell
$P = "D:\instalacao\gestor-pecas-deploy"
robocopy "$P\app" "D:\gestor-pecas" /E /NFL /NDL /NJH /NJS /XD docs tests .ai .agents .claude .codex .freebuff .github .impeccable .opencode
New-Item -ItemType Directory -Force -Path "D:\gestor-pecas\dados\logs","D:\gestor-pecas\backups","D:\gestor-pecas\dev_reports"
```
O `robocopy` devolve de 0 a 7 quando deu certo. Só 8 ou mais é erro.

### Passo 11 — Restringir o acesso à pasta
Só Administradores e SYSTEM entram. As contas dos serviços entram no passo 19.
```powershell
icacls "D:\gestor-pecas" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" /Q
```

---

## Parte D — Banco de dados

Já feita. Passo a passo em `INSTALACAO_BANCO.md`. Você precisa de duas coisas dela:
- a senha do usuário do sistema, no arquivo `D:\instalacao\senha-gestor_app.txt`
- a confirmação de que `select max(version) from schema_migrations` deu **68**

Para conferir de novo:
```powershell
$senhaApp = (Get-Content D:\instalacao\senha-gestor_app.txt).Trim()
$env:PGPASSWORD = $senhaApp
psql -h 127.0.0.1 -U gestor_app -d gestor_pecas -tAc "select max(version) from schema_migrations"
Remove-Item Env:PGPASSWORD
```
Esperado: `68`.

---

## Parte E — Arquivo `.env`

O `.env` é a configuração do sistema: `D:\gestor-pecas\.env`. Junta o `gestor.env.base` do pacote com um bloco gerado para esta máquina.

### Passo 12 — Gerar o `.env`
Confira o IP da VM (o último campo do bloco). Se o IP não for `192.168.0.230`, troque.
```powershell
$P = "D:\instalacao\gestor-pecas-deploy"
$senhaApp = (Get-Content D:\instalacao\senha-gestor_app.txt).Trim()
function Hex([int]$n) { $b = New-Object byte[] $n; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString("x2") }) }

$hosts   = "gestor-peca,$($env:COMPUTERNAME.ToLower()),localhost,127.0.0.1,192.168.0.230"
$origens = (($hosts -split ",") | ForEach-Object { "https://$_" }) -join ","

$linhas = @(
    "",
    "# --- Gerado manualmente em $(Get-Date -Format 'yyyy-MM-dd HH:mm') ---",
    "GESTOR_WEB_ENV=production",
    "DATABASE_URL=postgresql://gestor_app:$senhaApp@127.0.0.1:5432/gestor_pecas",
    "GESTOR_EXPECTED_DATABASE=gestor_pecas",
    "GESTOR_WEB_SESSION_SECRET=$(Hex 48)",
    "GESTOR_DEVOBS_SESSION_SECRET=$(Hex 48)",
    "GESTOR_WEB_COOKIE_SECURE=true",
    "GESTOR_WEB_SERVE_STATIC=true",
    "GESTOR_WEB_PUBLIC_HOST=gestor-peca",
    "GESTOR_WEB_ALLOWED_HOSTS=$hosts",
    "GESTOR_WEB_ALLOWED_ORIGINS=$origens",
    "GESTOR_DEV_OBSERVATORY_ENABLED=false",
    "TELEGRAM_ENABLED=true",
    "GESTOR_TELEGRAM_BOT_POLLING_ENABLED=true",
    "GESTOR_TELEGRAM_DIGEST_ENABLED=true",
    "GESTOR_OPERATOR_DRAWING_ROOTS="
)

$base = Get-Content -Raw -Encoding UTF8 "$P\gestor.env.base"
# UTF-8 SEM BOM: com BOM, a primeira chave do arquivo é lida errada
[IO.File]::WriteAllText("D:\gestor-pecas\.env", $base + ($linhas -join "`n") + "`n", (New-Object Text.UTF8Encoding $false))
```

### Passo 13 — Conferir o arquivo (sem mostrar senhas)
```powershell
Select-String -Path D:\gestor-pecas\.env -Pattern '^(GESTOR_WEB_ENV|GESTOR_EXPECTED_DATABASE|GESTOR_WEB_ALLOWED_HOSTS|GESTOR_TOTVS_OP_PULL_ENDPOINT)='
```
Esperado: as 3 ou 4 linhas. **Não pode** aparecer `gtsdo143182` (é o servidor de teste do Protheus).

### Passo 14 — Protheus REAL (4 campos `TROCAR`)
Abra `D:\gestor-pecas\.env` no Bloco de Notas (salve como **UTF-8**) e troque `TROCAR` pelo usuário e senha do Protheus REAL:
- `GESTOR_TOTVS_OUTBOUND_USERNAME` e `GESTOR_TOTVS_OUTBOUND_PASSWORD`
- `GESTOR_TOTVS_OP_PULL_USERNAME` e `GESTOR_TOTVS_OP_PULL_PASSWORD`

Pode ser feito agora ou depois. Enquanto estiver `TROCAR`, o envio e a busca de OPs no Protheus falham. O resto funciona. Depois de editar: `Restart-Service gestor-pecas`.

---

## Parte F — Ambiente Python

### Passo 15 — Criar o ambiente e instalar as dependências
Precisa de internet. Leva alguns minutos.
```powershell
py -3.14 -m venv D:\gestor-pecas\.venv
D:\gestor-pecas\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --require-hashes -r D:\gestor-pecas\requirements.lock
```
Esperado: termina com `Successfully installed ...`.
O `--require-hashes` confere cada pacote contra o `requirements.lock`. Se reclamar de hash, não tente contornar: me avise.

---

## Parte G — nginx (HTTPS)

### Passo 16 — Certificado e configuração
```powershell
$P = "D:\instalacao\gestor-pecas-deploy"
New-Item -ItemType Directory -Force -Path "C:\nginx\conf\certs" | Out-Null
Copy-Item "$P\certs\*" "C:\nginx\conf\certs\" -Force
icacls "C:\nginx\conf\certs" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" /Q
Copy-Item "$P\app\deploy\nginx.conf" "C:\nginx\conf\nginx.conf" -Force
```

### Passo 17 — Testar a configuração
```powershell
Push-Location C:\nginx
.\nginx.exe -t -p C:\nginx\
Pop-Location
```
Esperado: `syntax is ok` e `test is successful`.

---

## Parte H — Serviços do Windows

### Passo 18 — Registrar o sistema (`gestor-pecas`)
```powershell
$App = "D:\gestor-pecas"; $Svc = "gestor-pecas"; $Logs = "$App\dados\logs"
nssm install $Svc "$App\.venv\Scripts\python.exe"
nssm set $Svc AppParameters "-m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000"
nssm set $Svc AppDirectory $App
nssm set $Svc Start SERVICE_AUTO_START
nssm set $Svc AppExit Default Restart
nssm set $Svc AppEnvironmentExtra PYTHONUTF8=1
nssm set $Svc AppStdout "$Logs\gestor-pecas.log"
nssm set $Svc AppStderr "$Logs\gestor-pecas.log"
nssm set $Svc AppRotateFiles 1
nssm set $Svc AppRotateBytes 10485760
nssm set $Svc AppRotateOnline 1
```
Um processo só, só em `127.0.0.1`, sem `--workers`: o sistema tem tarefas internas que não são seguras com vários processos.

### Passo 19 — Rodar o sistema em conta própria (sem ser administrador)
No mesmo PowerShell do passo 18 (ou repita as duas primeiras linhas):
```powershell
$App = "D:\gestor-pecas"; $Svc = "gestor-pecas"
$Priv = "SeChangeNotifyPrivilege/SeCreateGlobalPrivilege"
sc.exe config $Svc obj= "NT SERVICE\$Svc"
sc.exe privs $Svc $Priv
icacls $App /grant "NT SERVICE\${Svc}:(OI)(CI)RX" /Q
foreach ($pasta in "$App\dados","$App\dev_reports") { icacls $pasta /grant "NT SERVICE\${Svc}:(OI)(CI)M" /Q }
```

### Passo 20 — Registrar o nginx do mesmo jeito
```powershell
$Priv = "SeChangeNotifyPrivilege/SeCreateGlobalPrivilege"
nssm install nginx "C:\nginx\nginx.exe"
nssm set nginx AppDirectory "C:\nginx"
nssm set nginx Start SERVICE_AUTO_START
nssm set nginx AppExit Default Restart
sc.exe config nginx obj= "NT SERVICE\nginx"
sc.exe privs nginx $Priv
icacls "C:\nginx" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" /Q
icacls "C:\nginx" /grant "NT SERVICE\nginx:(OI)(CI)RX" /Q
icacls "C:\nginx\conf\certs" /grant "NT SERVICE\nginx:(OI)(CI)R" /Q
foreach ($pasta in "C:\nginx\logs","C:\nginx\temp") {
    New-Item -ItemType Directory -Force -Path $pasta | Out-Null
    icacls $pasta /grant "NT SERVICE\nginx:(OI)(CI)M" /Q
}
```

### Passo 21 — Dar leitura ao `nssm.exe`
Os dois serviços usam o `nssm.exe` como executável.
```powershell
icacls "C:\tools\nssm" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" /Q
icacls "C:\tools\nssm" /grant "*S-1-5-11:(OI)(CI)RX" "*S-1-5-6:(OI)(CI)RX" /Q
```

### Passo 22 — Firewall
Abre só 80 e 443. As portas 8000 (sistema) e 5432 (banco) **não** são abertas.
```powershell
New-NetFirewallRule -DisplayName "Gestor de Pecas HTTPS" -Direction Inbound -Protocol TCP -LocalPort 80,443 -Action Allow
```

---

## Parte I — Ligar e conferir

### Passo 23 — Subir o sistema
Na primeira subida ele aplica migrações sozinho. Espere até 2 minutos.
```powershell
Start-Service gestor-pecas
Start-Sleep -Seconds 30
(Invoke-WebRequest http://127.0.0.1:8000/api/v1/system/ready -UseBasicParsing).StatusCode
```
Esperado: `200`. Se não responder, veja o log (e tente de novo depois de 1 minuto):
```powershell
Get-Content D:\gestor-pecas\dados\logs\gestor-pecas.log -Tail 50
```

### Passo 24 — Subir o nginx e testar o HTTPS
O Windows Server 2016 **não tem** o `curl.exe`. Use este teste, que aceita o certificado autoassinado:
```powershell
Start-Service nginx
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
(Invoke-WebRequest https://localhost/api/v1/system/ready -UseBasicParsing).StatusCode
```
Esperado: `200`. Se falhar, veja `C:\nginx\logs\error.log`.

### Passo 25 — Testar no navegador
Abra `https://localhost` na própria VM. O aviso de certificado é esperado. Entre com o login do sistema atual.

### Passo 26 — Conferir os serviços
```powershell
Get-Service gestor-pecas, nginx, postgresql*
```
Esperado: todos `Running`.

---

## Parte J — Backup diário

### Passo 27 — Copiar o script e proteger a pasta
A pasta de backup fica fora de `D:\gestor-pecas` de propósito.
```powershell
New-Item -ItemType Directory -Force C:\gestor-backup | Out-Null
icacls C:\gestor-backup /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" /Q
Copy-Item D:\gestor-pecas\deploy\backup_diario.ps1 C:\gestor-backup\backup_diario.ps1 -Force
```

### Passo 28 — (Opcional agora) Cópia fora da VM
Crie `C:\gestor-backup\copia-externa.txt` com uma linha: o caminho de rede (ex.: `\\servidor\backups\gestor-pecas`). A conta `NOME-DA-VM$` precisa de escrita nessa pasta.

### Passo 29 — Agendar para as 02:00 (guarda 14 dias)
```powershell
$acao = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\gestor-backup\backup_diario.ps1" -AppDir "D:\gestor-pecas" -PgBin "D:\postgresql\bin" -RetencaoDias 14'
$gatilho = New-ScheduledTaskTrigger -Daily -At "02:00"
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask "Gestor de Pecas - backup diario" -Action $acao -Trigger $gatilho -Principal $principal -Settings $ajustes -Force
```

### Passo 30 — Rodar uma vez agora e conferir
```powershell
Start-ScheduledTask "Gestor de Pecas - backup diario"
Start-Sleep -Seconds 60
Get-Content C:\gestor-backup\backup.log -Tail 5
Get-ChildItem D:\gestor-pecas\backups
```
Esperado: uma linha `OK ...diario-....dump` no log e um arquivo `diario-*.dump` na pasta.

---

## Parte K — Depois de instalar (para a fábrica usar)

### Passo 31 — IP fixo e nome
Reserve IP fixo para a VM e crie o nome `gestor-peca` no DNS. Os postos acessam `https://gestor-peca`.
Se o IP mudar, edite `GESTOR_WEB_ALLOWED_HOSTS` e `GESTOR_WEB_ALLOWED_ORIGINS` no `.env` e rode `Restart-Service gestor-pecas`.

### Passo 32 — Certificado da empresa
Troque `C:\nginx\conf\certs\gestor-pecas.crt` e `.key` (mesmos nomes) e rode `Restart-Service nginx`. Enquanto isso, o navegador avisa do certificado.

### Passo 33 — Protheus
- Credenciais REAL: passo 14.
- Para o Protheus enviar dados ao Gestor, coloque o IP de saída dele em `GESTOR_TOTVS_SOAP_ALLOWED_SOURCE_CIDRS` (ex.: `200.1.2.3/32`) e reinicie o serviço.

### Passo 34 — Desenhos dos operadores
Coloque o caminho de rede em `GESTOR_OPERATOR_DRAWING_ROOTS` (separados por `;`). A conta `NOME-DA-VM$` precisa de leitura nessa pasta.

### Passo 35 — Limpar o pacote
Tem o banco REAL, a chave do certificado e a senha do usuário do banco. **Só apague depois de tudo funcionando e do backup do passo 30 gerado.**
```powershell
Set-Location C:\
Remove-Item D:\instalacao -Recurse -Force
```

### Passo 36 — Senhas no cofre
Guarde a senha do `postgres` e a do `gestor_app` (está no `.env`) em um cofre. Não deixe arquivo com senha na VM.

### Passo 37 — Monitoramento
Alertas de disco > 80%, memória > 90% e serviços `gestor-pecas`, `nginx` e PostgreSQL parados.

### Passo 38 — Atualizações futuras
São manuais, empurradas do notebook do desenvolvedor (botão "Publicar na VM", via WinRM) ou pelo pipeline. O script de publicação assume `C:\gestor-pecas`: antes de usar, ajuste para `D:\gestor-pecas`. Ver `GUIA_TI.md` item 10 e `LEIA-ME.md`.

---

## Se algo der errado

- **Sistema não sobe:** `Get-Content D:\gestor-pecas\dados\logs\gestor-pecas.log -Tail 80`.
- **HTTPS não responde, mas `127.0.0.1:8000` sim:** é o nginx. Veja `C:\nginx\logs\error.log` e refaça o passo 17.
- **Erro de host/origem no login:** o endereço usado no navegador precisa estar em `GESTOR_WEB_ALLOWED_HOSTS` e `GESTOR_WEB_ALLOWED_ORIGINS`.
- **Erro de conexão com o banco:** confira se o serviço `postgresql*` está `Running` e se a senha no `DATABASE_URL` do `.env` é a de `D:\instalacao\senha-gestor_app.txt`.
- **Refazer o banco:** use o reset do `INSTALACAO_BANCO.md`. Nunca depois que a fábrica começou a usar a VM, sem backup.
- **Voltar atrás:** `Stop-Service gestor-pecas, nginx`. O notebook volta a ser o servidor (religue o Telegram em apenas um dos dois).
