# Requisitos de Infraestrutura — Gestor de Peças

**Ambiente:** Produção
**Sistema operacional:** Ubuntu Server 26.04 LTS
**Arquitetura:** x86-64 / AMD64
**Aplicação:** Gestor de Peças — MES Industrial Web
**Banco de dados:** PostgreSQL 17
**Backend:** Python 3.14 / FastAPI / Uvicorn
**Aprovado:** 18/09/2026, sem alterações — specs e dependências conferem com o que o projeto usa hoje ([requirements.txt](../requirements.txt), [compose.yaml](../compose.yaml)).

---

## 1. Objetivo

Define os requisitos de hardware e software para a VM de produção e o passo a passo para provisioná-la e ligar o deploy automático já preparado no repositório.

```text
Usuários / Postos / Gestão
          │
        HTTPS
          │
        Nginx
          │
   FastAPI / Uvicorn
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
| Swap | 4–8 GB | — |
| Rede | 1 Gbit/s | 1 Gbit/s |
| Arquitetura | x86-64 / AMD64 | x86-64 / AMD64 |

Disco obrigatoriamente SSD/NVMe (nunca HDD mecânico). Volume deve permitir expansão sem reinstalar a VM.

---

## 3. Software necessário

| Componente | Versão / finalidade |
| --- | --- |
| Ubuntu Server | 26.04 LTS |
| Python | 3.14 (venv próprio em `/opt/gestor-pecas/.venv`, nunca no Python global) |
| PostgreSQL | 17 |
| Nginx | reverse proxy / HTTPS |
| FastAPI / Uvicorn | backend Web (1 processo — ver §7) |
| Microsoft ODBC Driver | 18 |
| unixODBC / pyodbc | integração de leitura com o SQL Server do SigmaNEST |
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
| 22/TCP | administração SSH | restrita à rede administrativa |
| 8000/TCP | FastAPI/Uvicorn | somente interna |
| 5432/TCP | PostgreSQL | somente interna |

**Consequência para o deploy automático:** a VM não tem IP público nem porta de entrada exposta ao GitHub — por isso o pipeline usa um **runner self-hosted instalado dentro da própria VM** (ele puxa o job de dentro para fora; não precisa abrir porta nenhuma). Ver §8.

---

## 5. Segurança

- HTTPS com certificado corporativo; firewall ativo.
- Usuário exclusivo (não `root`) executando o serviço `gestor-pecas.service`.
- PostgreSQL e FastAPI não expostos à rede de usuários.
- Credenciais fora do código-fonte: `/etc/gestor-pecas/gestor.env`, acesso restrito ao usuário do serviço.
- Backup diário do PostgreSQL + cópia externa à VM. Snapshot da VM é complemento, nunca substituto.

---

## 6. Monitoramento

CPU, memória, disco, disponibilidade da VM, PostgreSQL, Nginx, serviço `gestor-pecas`. Alertas: disco > 80%, memória > 90% constante, serviço ou PostgreSQL indisponível.

---

## 7. Execução da aplicação

`systemd`, 1 processo Uvicorn (o projeto tem schedulers/tasks internos — outbox TOTVS com retry, digest de relatórios — que não são seguros para múltiplos workers sem coordenação adicional; não aumentar sem revisar isso antes).

```ini
# /etc/systemd/system/gestor-pecas.service (referência)
[Service]
User=gestor-pecas
EnvironmentFile=/etc/gestor-pecas/gestor.env
WorkingDirectory=/opt/gestor-pecas
ExecStart=/opt/gestor-pecas/.venv/bin/python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
```

Migrations aplicam automaticamente na inicialização do processo (`auto_migrate` em `app/database/database.py`) — não é um passo manual separado.

---

## 8. Pipeline de CI/CD (já implementado, 18/09/2026)

O repositório já está automatizado e não depende mais de zip/pendrive/SCP manual:

- **[.github/workflows/ci.yml](../.github/workflows/ci.yml)** — a cada push: testes do backend (Postgres 17 de serviço) + build/testes do frontend. Já verde.
- **[.github/workflows/deploy.yml](../.github/workflows/deploy.yml)** — builda o frontend e implanta na VM. **Dispara só por tag de release** (`git tag vX.Y.Z && git push --tags`), nunca em push comum — decisão deliberada para não implantar em produção algo ainda em teste na `master`.
- Todo commit local já sincroniza sozinho com o GitHub (hook `post-commit`).

O job de deploy roda num **self-hosted runner instalado na própria VM**, com a label `gestor-pecas-vm`. Até a VM existir e o runner ser instalado, o workflow fica só esperando — não falha, não faz nada.

---

## 9. To-do — provisionamento e primeiro deploy

Ordem sugerida, do zero até o primeiro deploy automático funcionando:

- [ ] **Pedir a VM** para a TI com as specs da §2 (recomendado: 8 vCPU / 16 GB / 200 GB SSD) e §4 (IP fixo, DNS interno, portas).
- [ ] **Instalar o sistema base**: Ubuntu Server 26.04 LTS, NTP, firewall (liberar só 443/80 públicas e 22 restrita à rede administrativa).
- [ ] **Instalar dependências de sistema**: Python 3.14, PostgreSQL 17, Nginx, Microsoft ODBC Driver 18, unixODBC.
- [ ] **Criar o PostgreSQL de produção**: banco + usuário dedicado (nunca reaproveitar credencial de homologação — ver achado de segurança de 18/09/2026 sobre credencial exposta).
- [ ] **Criar estrutura da aplicação**: usuário de serviço `gestor-pecas` (não-root), `/opt/gestor-pecas`, `.venv` próprio, `/etc/gestor-pecas/gestor.env` com as credenciais reais (banco, TOTVS, Telegram, `GESTOR_WEB_SESSION_SECRET`, `GESTOR_DEVOBS_SESSION_SECRET`, `GESTOR_WEB_SERVE_STATIC=true`).
- [ ] **Criar o serviço systemd** `gestor-pecas.service` (referência em §7) e o site do Nginx com HTTPS (certificado corporativo) fazendo proxy para `127.0.0.1:8000`.
- [ ] **Registrar o runner self-hosted do GitHub Actions na VM**: Settings → Actions → Runners → *New self-hosted runner*, label `gestor-pecas-vm`. O runner precisa conseguir: `sudo rsync`, `sudo systemctl restart gestor-pecas.service` e `curl 127.0.0.1:8000` sem senha interativa (sudoers dedicado, não o usuário do serviço).
- [ ] **Primeiro deploy manual** (antes de confiar no pipeline): validar o checklist do [WEB_DEPLOYMENT.md](WEB_DEPLOYMENT.md) na própria VM — health check, login/CSRF, posto real, virada de turno.
- [ ] **Disparar a primeira tag**: `git tag v1.0.0 && git push --tags` — confirma que o pipeline builda e implanta sozinho.
- [ ] **Configurar backup do PostgreSQL** (diário + cópia externa) e os alertas de monitoramento da §6.
- [ ] **Confirmar rollback**: trocar a tag/versão do serviço, nunca limpar banco ou reescrever produção (regra já vale para o processo manual, continua valendo com o pipeline).

Pendências que dependem de decisão do usuário, não de infraestrutura:
- Rotacionar a senha do SQL Server do TOTVS (`sql_ppi`) usada em homologação — decidiu não rotacionar por ora (ambiente descartável); reavaliar antes de ir para produção real.
- As 3 pendências abertas da auditoria de segurança de 14/09/2026 (freio no login principal, IDOR na Qualidade, session secrets ausentes no `.env`) — resolver antes ou durante este provisionamento, já que a VM de produção é o ambiente onde elas importam de fato.
