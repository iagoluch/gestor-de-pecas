# Requisitos de Infraestrutura — Gestor de Peças

**Ambiente:** Produção
**Sistema operacional:** Windows Server 2025
**Arquitetura:** x86-64 / AMD64
**Aplicação:** Gestor de Peças — MES Industrial Web
**Banco de dados:** PostgreSQL 17
**Backend:** Python 3.14 / FastAPI / Uvicorn
**Atualizado:** 21/09/2026 — a infra confirmou que o SO da VM será Windows Server 2025 (ano-modelo pode variar, mas já é certo que é linha Windows Server), substituindo a proposta original de Ubuntu Server. Hardware, banco de dados e dependências Python continuam os mesmos; mudou o sistema operacional e, por consequência, como o serviço roda e como o proxy reverso é montado.

---

## 1. Objetivo

Define os requisitos de hardware e software para a VM de produção (Windows Server 2025) e o passo a passo para provisioná-la e ligar o deploy automático já preparado no repositório.

```text
Usuários / Postos / Gestão
          │
        HTTPS
          │
   nginx para Windows
          │
   FastAPI / Uvicorn (Serviço do Windows via NSSM)
          │
      PostgreSQL
          │
   Integrações externas (TOTVS, SigmaNEST, Telegram, IA)
```

Aplicação e banco PostgreSQL na mesma VM na implantação inicial.

---

## 2. Hardware

| Recurso | Recomendado (produção) | Mínimo (homologação) |
| --- | ---: | ---: |
| Processador | 8 vCPU | 4 vCPU |
| Memória RAM | 16 GB | 8 GB |
| Armazenamento | 200 GB SSD/NVMe | 100 GB SSD |
| Rede | 1 Gbit/s | 1 Gbit/s |
| Arquitetura | x86-64 / AMD64 | x86-64 / AMD64 |

Disco obrigatoriamente SSD/NVMe (nunca HD mecânico). Volume deve permitir expansão sem reinstalar a VM.

---

## 3. Software necessário

| Componente | Versão / finalidade |
| --- | --- |
| Windows Server | 2025 |
| Python | 3.14 (venv próprio em `C:\gestor-pecas\.venv`, nunca no Python global) |
| PostgreSQL | 17 |
| nginx para Windows | reverse proxy / HTTPS |
| NSSM | expõe o processo Uvicorn como Serviço do Windows (início automático, reinício em falha) |
| Driver ODBC 18 da Microsoft para SQL Server | integração de leitura com o banco do SigmaNEST — no Windows é só instalar o driver nativo, sem unixODBC (isso era exigência específica do Linux) |
| Node.js | **não é requisito de execução** — o frontend (`web/dist`) já vem construído pelo pipeline de deploy |

Dependências Python: ver [requirements.txt](../requirements.txt) — FastAPI, Uvicorn, psycopg[binary]+psycopg_pool, pyodbc (sob demanda), openpyxl, httpx, python-dotenv, defusedxml, groq.

---

## 4. Rede e portas

```text
IP fixo/reservado, DNS interno, NTP, HTTPS
```

| Porta | Uso | Exposição |
| ---: | --- | --- |
| 443/TCP | HTTPS | pública (usuários) |
| 80/TCP | redirecionamento para HTTPS | pública (opcional) |
| 3389/TCP | administração remota (RDP) | restrita à rede administrativa |
| 5985/TCP | WinRM, se a automação de infraestrutura precisar | restrita à rede administrativa |
| 8000/TCP | FastAPI/Uvicorn | somente interna (o Windows Firewall deve bloquear origem externa) |
| 5432/TCP | PostgreSQL | somente interna |

**Consequência para o deploy automático:** a VM não tem IP público nem porta de entrada exposta ao GitHub — por isso o pipeline usa um **runner self-hosted do GitHub Actions instalado dentro da própria VM** (ele puxa o job de dentro para fora; não precisa abrir porta nenhuma). Ver §8.

---

## 5. Segurança

- HTTPS com certificado corporativo; Windows Defender Firewall ativo, liberando só as portas da §4.
- Conta de serviço dedicada (nunca a conta `Administrador`) rodando o serviço `gestor-pecas`.
- PostgreSQL e Uvicorn não expostos à rede de usuários — só o nginx conversa com fora.
- Credenciais fora do código-fonte, num arquivo de ambiente lido pelo NSSM (ex.: `C:\gestor-pecas\gestor.env`), com permissão de leitura restrita à conta de serviço.
- Backup diário do PostgreSQL + cópia externa à VM. Snapshot da VM é complemento, nunca substituto.

---

## 6. Monitoramento

CPU, memória, disco, disponibilidade da VM, PostgreSQL, nginx, serviço `gestor-pecas`. Alertas: disco > 80%, memória > 90% constante, serviço ou PostgreSQL indisponível.

---

## 7. Execução da aplicação

Serviço do Windows registrado via **NSSM**, 1 processo Uvicorn (o projeto tem schedulers/tasks internos — outbox TOTVS com retry, digest de relatórios — que não são seguros para múltiplos workers sem coordenação adicional; não aumentar sem revisar isso antes).

```powershell
# Registro do serviço (referência, roda uma vez na preparação da VM)
nssm install gestor-pecas "C:\gestor-pecas\.venv\Scripts\python.exe" `
  "-m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000"
nssm set gestor-pecas AppDirectory "C:\gestor-pecas"
nssm set gestor-pecas AppEnvironmentExtra (Get-Content C:\gestor-pecas\gestor.env)
nssm set gestor-pecas Start SERVICE_AUTO_START
nssm set gestor-pecas AppExit Default Restart
```

Depois de registrado, o serviço aparece como qualquer outro Serviço do Windows (`services.msc` ou `Get-Service gestor-pecas`), e reiniciar/parar/consultar status usa os comandos nativos do PowerShell (`Restart-Service`, `Stop-Service`).

Migrations aplicam automaticamente na inicialização do processo (`auto_migrate` em `app/database/database.py`) — não é um passo manual separado.

---

## 8. Pipeline de CI/CD (já implementado)

O repositório já está automatizado e não depende de zip/pendrive/cópia manual:

- **[.github/workflows/ci.yml](../.github/workflows/ci.yml)** — a cada push: testes do backend (Postgres 17 de serviço), build/testes do frontend e verificações de segurança (segredos vazados, dependências vulneráveis, padrões inseguros). Já verde.
- **[.github/workflows/deploy.yml](../.github/workflows/deploy.yml)** — builda o frontend e implanta na VM. **Dispara só por tag de release** (`git tag vX.Y.Z && git push --tags`), nunca em push comum — decisão deliberada para não implantar em produção algo ainda em teste na `master`. O primeiro job do deploy reexecuta o CI completo para o mesmo commit da tag; nenhum deploy acontece se essa validação não passar.
- Todo commit local já sincroniza sozinho com o GitHub (hook `post-commit`).

O job de deploy roda num **runner self-hosted do GitHub Actions instalado na própria VM Windows**, com a label `gestor-pecas-vm`. Ele usa `robocopy` (equivalente Windows do rsync) para levar o código até `C:\gestor-pecas`, sem tocar no `.venv` nem no arquivo de credenciais, e reinicia o serviço via PowerShell. Até a VM existir e o runner ser instalado, o workflow fica só esperando — não falha, não faz nada.

---

## 9. To-do — provisionamento e primeiro deploy

Ordem sugerida, do zero até o primeiro deploy automático funcionando:

- [ ] **Confirmar com a infra** a versão exata do Windows Server (2025 ou outra da mesma linha) e as specs da §2 (recomendado: 8 vCPU / 16 GB / 200 GB SSD) e §4 (IP fixo, DNS interno, portas).
- [ ] **Instalar o sistema base**: Windows Server atualizado (Windows Update em dia), NTP, Windows Defender Firewall liberando só 443/80 públicas e 3389 (RDP) restrita à rede administrativa.
- [ ] **Instalar dependências de sistema**: Python 3.14, PostgreSQL 17, nginx para Windows, NSSM, driver ODBC 18 da Microsoft para SQL Server.
- [ ] **Criar o PostgreSQL de produção**: banco + usuário dedicado (nunca reaproveitar credencial de homologação).
- [ ] **Criar estrutura da aplicação**: conta de serviço dedicada (não a conta Administrador), pasta `C:\gestor-pecas`, `.venv` próprio dentro dela, arquivo de ambiente (`gestor.env`) com as credenciais reais (banco, TOTVS, Telegram, `GESTOR_WEB_SESSION_SECRET`, `GESTOR_DEVOBS_SESSION_SECRET`, `GESTOR_WEB_SERVE_STATIC=true`).
- [ ] **Registrar o serviço `gestor-pecas` via NSSM** (referência em §7) e configurar o nginx para Windows com HTTPS (certificado corporativo) fazendo proxy para `127.0.0.1:8000`.
- [ ] **Instalar o runner self-hosted do GitHub Actions na VM (versão Windows)**: Settings → Actions → Runners → *New self-hosted runner*, escolher Windows, label `gestor-pecas-vm`. A conta que roda o runner precisa conseguir reiniciar o serviço `gestor-pecas` e escrever em `C:\gestor-pecas` sem prompt interativo.
- [ ] **Primeiro deploy manual** (antes de confiar no pipeline): validar o checklist do [WEB_DEPLOYMENT.md](WEB_DEPLOYMENT.md) na própria VM — health check, login/CSRF, posto real, virada de turno.
- [ ] **Disparar a primeira tag**: `git tag v1.0.0 && git push --tags` — confirma que o pipeline builda e implanta sozinho.
- [ ] **Configurar backup do PostgreSQL** (diário + cópia externa) e os alertas de monitoramento da §6.
- [ ] **Confirmar rollback**: trocar a tag/versão do serviço, nunca limpar banco ou reescrever produção (regra já vale para o processo manual, continua valendo com o pipeline).
