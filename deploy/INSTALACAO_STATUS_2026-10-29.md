# Gestor de Peças — instalação na VM: o que já foi feito e o que falta

Servidor: **SVR-TMES** (Windows Server 2016) · IP 192.168.0.230 · conferido em **29/10/2026, 14:32**
Para: líder da TI · Base: `INSTALACAO_MANUAL.md` (os números dos passos são os mesmos)

## Resumo em 30 segundos

- **Pronto:** banco de dados, Python, ODBC, código do sistema, ambiente Python (`.venv`) e `.env` (quase todo).
- **Falta:** transformar o sistema e o nginx em serviços do Windows, abrir o firewall, ligar tudo e agendar o backup.
- **Por que parou:** quem está instalando **não tem Administrador** na VM. Todos os passos que faltam exigem Administrador.
- **O que preciso do líder da TI (3 coisas):**
  1. Um PowerShell **como Administrador** na VM (ou alguém da TI rodar os passos abaixo).
  2. Usuário e senha do **Protheus REAL** (4 campos no `.env`).
  3. Confirmar o **nome/IP** pelo qual os postos vão abrir o sistema (ex.: `https://gestor-peca` ou `https://192.168.0.230`).

Tempo estimado do que falta: **cerca de 1 hora**, com Administrador.

## Situação, passo a passo

Legenda: ✅ feito e conferido · ❌ falta fazer · ❓ não dá para conferir pelo script (alguém confirma)

### Parte A — Preparação

| Passo | O que é | Situação |
|---|---|---|
| 1 | Pacote em `D:\instalacao\gestor-pecas-deploy` | ✅ |
| 2 | Fuso de Brasília (turnos e OEE dependem disso) | ❓ conferir: `(Get-TimeZone).Id` deve dar `E. South America Standard Time` |
| 3 | Telegram do notebook desligado (o bot é o mesmo; ligado nos dois, responde duplicado) | ❓ combinar com quem usa o notebook |
| 4 | Data da "virada" (o banco da VM é uma cópia de 28/10 às 15:04; o que for apontado no notebook depois disso não chega na VM) | ❓ **decisão da gestão: qual dia a fábrica passa a usar a VM** |

### Parte B — Programas

| Passo | O que é | Situação |
|---|---|---|
| 5 | Python 3.14 (instalado para todos os usuários) | ✅ `Python 3.14.10` responde. Conferir ainda que o caminho não é de usuário: `py -3.14 -c "import sys; print(sys.base_prefix)"` não pode começar com `C:\Users\` |
| 6 | nginx | ✅ **já instalado em `D:\nginx-1.30.6`** (não em `C:\nginx`, como o manual supunha). Daqui para frente usamos esse caminho. |
| 7 | NSSM (transforma o sistema em serviço) | ✅ programa em `C:\tools\nssm\nssm.exe` · ❌ **falta colocar a pasta no PATH** (precisa Administrador) |
| 8 | ODBC Driver 18 | ✅ |
| 9 | Conferência geral (`nssm version`, `psql --version`...) | ❌ refazer depois do passo 7, em PowerShell novo |

### Parte C — Código e pastas

| Passo | O que é | Situação |
|---|---|---|
| 10 | Código em `D:\gestor-pecas` com `dados\logs`, `backups`, `dev_reports` | ✅ |
| 11 | Restringir o acesso à pasta (só Administradores e SYSTEM) | ❌ hoje ainda há acesso para "Users/Everyone". Precisa Administrador |

### Parte D — Banco de dados

| Passo | O que é | Situação |
|---|---|---|
| — | PostgreSQL 17 rodando em `D:\postgresql`; banco `gestor_pecas` na versão **68** | ✅ |

### Parte E — Arquivo `.env`

| Passo | O que é | Situação |
|---|---|---|
| 12–13 | `.env` criado em `D:\gestor-pecas\.env`, sem BOM | ✅ |
| 14 | Usuário/senha do **Protheus REAL** | ❌ 4 campos ainda com `TROCAR`: `GESTOR_TOTVS_OUTBOUND_USERNAME`, `GESTOR_TOTVS_OUTBOUND_PASSWORD`, `GESTOR_TOTVS_OP_PULL_USERNAME`, `GESTOR_TOTVS_OP_PULL_PASSWORD`. Enquanto estiverem assim, o envio e a busca de OPs no Protheus falham; o resto do sistema funciona. |
| — | `GESTOR_OPERATOR_DRAWING_ROOTS` vazio | ℹ️ normal por enquanto (caminho dos desenhos, passo 34) |
| — | `TELEGRAM_ENABLED=true` | ⚠️ confirmar o passo 3 antes de ligar o serviço |
| — | `GESTOR_TOTVS_OUTBOX_ENABLED=false` | ℹ️ proposital: o envio automático para o Protheus fica desligado até a virada |

### Parte F — Ambiente Python

| Passo | O que é | Situação |
|---|---|---|
| 15 | `.venv` criado e pacotes instalados | ✅ |

### Parte G — nginx (HTTPS)

| Passo | O que é | Situação |
|---|---|---|
| 16 | Copiar certificado e `nginx.conf` para o nginx | ❌ |
| 17 | Testar a configuração (`nginx -t`) | ❌ |

### Parte H — Serviços do Windows

| Passo | O que é | Situação |
|---|---|---|
| 18 | Serviço `gestor-pecas` | ❌ não existe |
| 19 | Rodar `gestor-pecas` em conta própria (sem Administrador) | ❌ |
| 20 | Serviço `nginx` | ❌ não existe |
| 21 | Leitura do `nssm.exe` para as contas dos serviços | ❌ |
| 22 | Firewall: abrir 80 e 443 | ❌ |

### Parte I — Ligar e conferir

| Passo | O que é | Situação |
|---|---|---|
| 23–26 | Subir o sistema e o nginx; testar no navegador | ❌ hoje só o PostgreSQL escuta (porta 5432); nada responde em 8000/443 |

### Parte J — Backup diário

| Passo | O que é | Situação |
|---|---|---|
| 27–30 | Pasta `C:\gestor-backup`, agendamento às 02:00, teste | ❌ a pasta não existe. As tarefas `BackupTask` e `RegIdleBackup` que apareceram são do Windows, **não** são o nosso backup |

### Parte K — Depois de instalar

| Passo | O que é | Situação |
|---|---|---|
| 31–38 | IP fixo e nome `gestor-peca` no DNS, certificado da empresa, Protheus, desenhos, limpar o pacote, cofre de senhas, monitoramento | ❌ a fazer depois que o sistema estiver no ar. Passo 35 (apagar `D:\instalacao`) **só depois** do backup do passo 30 gerado. |

---

## O que fazer agora (para quem tem Administrador)

Abra o **PowerShell como Administrador** na VM. O caminho do nginx neste roteiro é o real: `D:\nginx-1.30.6`.

### 1. PATH do NSSM (passo 7) e conferência (passo 9)
```powershell
$p = [Environment]::GetEnvironmentVariable("Path","Machine")
if (($p -split ";") -notcontains "C:\tools\nssm") { [Environment]::SetEnvironmentVariable("Path","$p;C:\tools\nssm","Machine") }
```
Feche o PowerShell, abra outro como Administrador e confira que os quatro respondem:
```powershell
nssm version; psql --version; py -3.14 --version; Get-OdbcDriver -Name "ODBC Driver 18 for SQL Server"
```

### 2. Restringir a pasta do sistema (passo 11)
```powershell
icacls "D:\gestor-pecas" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" /Q
```

### 3. Protheus REAL (passo 14)
Abrir `D:\gestor-pecas\.env` no Bloco de Notas, trocar os 4 `TROCAR` pelos valores do Protheus REAL e salvar como **UTF-8**. Pode ficar para depois do sistema no ar.

### 4. nginx: certificado e configuração (passos 16–17)
```powershell
$P = "D:\instalacao\gestor-pecas-deploy"; $Ngx = "D:\nginx-1.30.6"
New-Item -ItemType Directory -Force -Path "$Ngx\conf\certs" | Out-Null
Copy-Item "$P\certs\*" "$Ngx\conf\certs\" -Force
icacls "$Ngx\conf\certs" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" /Q
Copy-Item "$P\app\deploy\nginx.conf" "$Ngx\conf\nginx.conf" -Force
Push-Location $Ngx; .\nginx.exe -t -p "$Ngx\"; Pop-Location
```
Esperado: `syntax is ok` e `test is successful`.
Se já havia um `nginx.conf` em uso nesta máquina, **guarde uma cópia antes** de sobrescrever.

### 5. Serviço do sistema (passos 18–19)
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

$Priv = "SeChangeNotifyPrivilege/SeCreateGlobalPrivilege"
sc.exe config $Svc obj= "NT SERVICE\$Svc"
sc.exe privs $Svc $Priv
icacls $App /grant "NT SERVICE\${Svc}:(OI)(CI)RX" /Q
foreach ($pasta in "$App\dados","$App\dev_reports") { icacls $pasta /grant "NT SERVICE\${Svc}:(OI)(CI)M" /Q }
```
Um processo só, só em `127.0.0.1`, **sem** `--workers`: o sistema tem tarefas internas que não são seguras com vários processos.

### 6. Serviço do nginx (passo 20)
```powershell
$Ngx = "D:\nginx-1.30.6"; $Priv = "SeChangeNotifyPrivilege/SeCreateGlobalPrivilege"
nssm install nginx "$Ngx\nginx.exe"
nssm set nginx AppDirectory $Ngx
nssm set nginx Start SERVICE_AUTO_START
nssm set nginx AppExit Default Restart
sc.exe config nginx obj= "NT SERVICE\nginx"
sc.exe privs nginx $Priv
icacls $Ngx /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" /Q
icacls $Ngx /grant "NT SERVICE\nginx:(OI)(CI)RX" /Q
icacls "$Ngx\conf\certs" /grant "NT SERVICE\nginx:(OI)(CI)R" /Q
foreach ($pasta in "$Ngx\logs","$Ngx\temp") {
    New-Item -ItemType Directory -Force -Path $pasta | Out-Null
    icacls $pasta /grant "NT SERVICE\nginx:(OI)(CI)M" /Q
}
```

### 7. Leitura do `nssm.exe` e firewall (passos 21–22)
```powershell
icacls "C:\tools\nssm" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" /Q
icacls "C:\tools\nssm" /grant "*S-1-5-11:(OI)(CI)RX" "*S-1-5-6:(OI)(CI)RX" /Q
New-NetFirewallRule -DisplayName "Gestor de Pecas HTTPS" -Direction Inbound -Protocol TCP -LocalPort 80,443 -Action Allow
```
As portas 8000 (sistema) e 5432 (banco) **não** são abertas.

### 8. Ligar e conferir (passos 23–26)
```powershell
Start-Service gestor-pecas
Start-Sleep -Seconds 30
(Invoke-WebRequest http://127.0.0.1:8000/api/v1/system/ready -UseBasicParsing).StatusCode

Start-Service nginx
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
(Invoke-WebRequest https://localhost/api/v1/system/ready -UseBasicParsing).StatusCode

Get-Service gestor-pecas, nginx, postgresql*
```
Esperado: `200`, `200` e os três serviços `Running`. Na primeira subida o sistema aplica migrações sozinho (até 2 minutos). Se não responder:
```powershell
Get-Content D:\gestor-pecas\dados\logs\gestor-pecas.log -Tail 50
Get-Content D:\nginx-1.30.6\logs\error.log -Tail 30
```
Depois abra `https://localhost` no navegador da VM (o aviso de certificado é esperado).

### 9. Backup diário (passos 27–30)
```powershell
New-Item -ItemType Directory -Force C:\gestor-backup | Out-Null
icacls C:\gestor-backup /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" /Q
Copy-Item D:\gestor-pecas\deploy\backup_diario.ps1 C:\gestor-backup\backup_diario.ps1 -Force

$acao = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\gestor-backup\backup_diario.ps1" -AppDir "D:\gestor-pecas" -PgBin "D:\postgresql\bin" -RetencaoDias 14'
$gatilho = New-ScheduledTaskTrigger -Daily -At "02:00"
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask "Gestor de Pecas - backup diario" -Action $acao -Trigger $gatilho -Principal $principal -Settings $ajustes -Force

Start-ScheduledTask "Gestor de Pecas - backup diario"
Start-Sleep -Seconds 60
Get-Content C:\gestor-backup\backup.log -Tail 5
Get-ChildItem D:\gestor-pecas\backups
```
Esperado: uma linha `OK ...diario-....dump` no log e um arquivo `diario-*.dump` na pasta.
Opcional agora: cópia fora da VM (passo 28 do manual).

### 10. Conferir tudo de uma vez
Rode de novo `verificar_instalacao.ps1` (na pasta `deploy`) e mande o resultado: tudo deve sair `[OK]`, exceto os 4 `TROCAR` do Protheus enquanto não forem preenchidos.

---

## Antes de a fábrica usar

1. Decidir a **data da virada** (passo 4) e desligar o Telegram do notebook (passo 3).
2. IP fixo para a VM e nome `gestor-peca` no DNS (passo 31). Se o IP mudar, ajustar `GESTOR_WEB_ALLOWED_HOSTS` e `GESTOR_WEB_ALLOWED_ORIGINS` no `.env` e rodar `Restart-Service gestor-pecas`.
3. Certificado da empresa no lugar do autoassinado (passo 32): trocar `gestor-pecas.crt` e `.key` em `D:\nginx-1.30.6\conf\certs` e `Restart-Service nginx`.
4. Credenciais do Protheus REAL e IP de saída do Protheus em `GESTOR_TOTVS_SOAP_ALLOWED_SOURCE_CIDRS` (passos 14 e 33).
5. Só então apagar `D:\instalacao` (tem o banco REAL, a chave do certificado e a senha do banco) e guardar as senhas no cofre (passos 35–36).

## Riscos em aberto

- **Python 3.14, PostgreSQL 17 e ODBC 18 no Windows Server 2016**: Python e PostgreSQL já rodam aqui; o ODBC está instalado. O sistema em si ainda não foi ligado nesta VM, então a prova final é o passo 8.
- **Banco da VM é de 28/10, 15:04**: tudo que for apontado no notebook depois disso não está na VM.
- **Windows Server 2016 "Evaluation"**: versão de avaliação, que expira. Confirmar o licenciamento definitivo com a TI.
