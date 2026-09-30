# Primeira instalação do Gestor de Peças na VM

Roteiro da instalação do zero (Windows Server + PostgreSQL 17 nativo + nginx +
NSSM). Os deploys seguintes são automáticos pelo pipeline
(`.github/workflows/deploy.yml`, tag `v*`).

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

A única pergunta é a senha do `postgres`, e ela é pulada quando o `instalar_prerequisitos.ps1` gerou o `postgres-senha.txt`. O script executa, nesta ordem:

1. confere os pré-requisitos;
2. copia o código para `C:\gestor-pecas` e restringe a pasta a Administradores e SYSTEM;
3. cria o role `gestor_app` com uma senha nova e restaura o dump no banco `gestor_pecas`;
4. gera o `.env` com segredos novos e os hosts da VM;
5. cria a `.venv` com as dependências do `requirements.lock`;
6. configura o nginx com HTTPS;
7. registra os serviços `gestor-pecas` e `nginx`;
8. libera as portas 80/443 no firewall;
9. valida `/api/v1/system/ready` direto no Uvicorn e através do nginx.

Pode rodar de novo sem risco:

- banco e `.env` já existentes são mantidos;
- se o restore falhar, o banco incompleto é apagado;
- para restaurar um dump mais novo, rode `DROP DATABASE gestor_pecas` como `postgres` e execute de novo. A senha do `.env` é reaproveitada.

Depois do sucesso, **apague `C:\instalacao`**: o dump do REAL e a chave do certificado ficam lá sem restrição de acesso. Antes, guarde num cofre a senha do `postgres` (`postgres-senha.txt`, se veio do script): ela é necessária para `DROP DATABASE` e manutenção.

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

## 6. Diferenças conhecidas em relação ao servidor definitivo

- Certificado autoassinado → trocar pelo corporativo, com os mesmos nomes de arquivo em `C:\nginx\conf\certs`.
- Serviço roda como LocalSystem → no servidor definitivo, usar uma conta de serviço dedicada com leitura do `.env`.
- `GESTOR_OPERATOR_DRAWING_ROOTS` vazio → preencher com o caminho de rede real dos desenhos.
- `C:\nginx\conf\nginx.conf` só é copiado na instalação. O pipeline não o atualiza: ao mudar `deploy/nginx.conf`, copie-o à mão e rode `Restart-Service nginx`.
- Runner do GitHub Actions (§9 de `docs/REQUISITOS_INFRAESTRUTURA_VM.md`):
  - a conta dele precisa ler o `.env` (o backup pré-deploy tira a `DATABASE_URL` de lá);
  - precisa parar e iniciar o serviço `gestor-pecas`;
  - precisa escrever em `C:\gestor-pecas`.
  - A conta padrão do runner (NETWORK SERVICE) não faz nada disso. Como `C:\gestor-pecas` fica restrito, conceda acesso à conta escolhida com `icacls C:\gestor-pecas /grant "<conta>:(OI)(CI)M"`.
  - Instale o runner depois deste script, ou reinicie o serviço dele: só assim ele enxerga o `pg_dump` no PATH.
