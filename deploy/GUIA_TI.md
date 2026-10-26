# Gestor de Peças — guia da instalação na VM

Para quem instala (TI). Duas partes: **instalar** (30–40 min, quase tudo automático) e **configurar depois** (itens que só a TI resolve).

## Parte 1 — Instalar

O que você precisa: a VM com Windows Server 2025, internet liberada, 15 GB livres em `C:` e acesso de Administrador.

1. Copie `gestor-pecas-deploy.zip` para a VM, por exemplo para `C:\instalacao\`.
2. Extraia o zip ali mesmo. Vai nascer a pasta `C:\instalacao\gestor-pecas-deploy`.
3. **Jeito fácil:** dentro de `gestor-pecas-deploypp\deploy`, dê duplo clique em `Instalar na VM.bat` (ele pede Administrador sozinho) e pule para o passo 5.
   Se o duplo clique for bloqueado, abra o **PowerShell como Administrador**.
4. Rode:
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\instalacao\gestor-pecas-deploy\app\deploy\instalar.ps1
   ```
5. O script faz uma pergunta no começo. Responda **Enter** nas duas (ficam para depois):
   - *Pasta externa do backup* → Enter (o backup fica só local por enquanto).
6. Espere. O PostgreSQL demora uns 20 min. Não feche a janela.
7. No fim aparece um **CHECKLIST**. Esperado: `[OK]` em *gestor-pecas rodando*, *nginx rodando* e *ready responde 200*.
8. Teste: abra <https://localhost> na própria VM. O navegador avisa do certificado (é autoassinado, normal). O login é o mesmo do sistema atual.

O que o instalador já deixa pronto: Python, PostgreSQL 17, nginx, NSSM, driver ODBC, o sistema como serviço do Windows (`gestor-pecas`), HTTPS, banco restaurado, firewall 80/443 e backup diário às 02:00 (local).

Se algo falhar: corrija e rode o mesmo comando de novo. É seguro repetir.

Logs: `C:\gestor-pecas\dados\logs\gestor-pecas.log` e `C:\nginx\logs\error.log`.

## Parte 2 — Configurar depois (o que o instalador não faz)

Em ordem de importância. Os itens 1–3 são necessários para a fábrica usar.

1. **Nome e IP**: reserve IP fixo e crie o nome interno `gestor-peca` no DNS. Nas máquinas dos postos, o endereço é <https://gestor-peca>.
   - Se o IP da VM mudar depois da instalação, edite `GESTOR_WEB_ALLOWED_HOSTS` e `GESTOR_WEB_ALLOWED_ORIGINS` em `C:\gestor-pecas\.env` e rode `Restart-Service gestor-pecas`.
2. **Certificado corporativo**: troque o autoassinado para tirar o aviso do navegador. Substitua os arquivos `gestor-pecas.crt` e `gestor-pecas.key` em `C:\nginx\conf\certs` (mesmos nomes) e rode `Restart-Service nginx`.
3. **Hora da VM**: confira `w32tm /query /status` e compare com um relógio confiável. Apontamento e OEE dependem da hora certa.
4. **Cópia externa do backup**: o backup diário já roda, mas só dentro da VM. Crie `C:\gestor-backup\copia-externa.txt` com uma linha: o caminho de rede (ex.: `\\servidor\backups\gestor-pecas`). A conta `NOME-DA-VM$` precisa de escrita nessa pasta. Depois rode a tarefa "Gestor de Pecas - backup diario" uma vez e confira o `C:\gestor-backup\backup.log`.
5. **Senha do PostgreSQL**: está em `C:\gestor-backup\postgres-senha.txt` (ou em `C:\instalacao\gestor-pecas-deploy\postgres-senha.txt`). Guarde em um cofre e **apague o arquivo**.
6. **Pacote**: o instalador já apaga `C:\instalacao` (tem o banco real e a chave do certificado) ao terminar. Se o checklist avisar que ficou, apague à mão.
7. **Protheus REAL**: o pacote traz o Protheus REAL só se o PCP preencheu os dados antes de montá-lo. Confira no checklist final: `Protheus REAL configurado no .env`. Se estiver `[PENDENTE]`, edite `C:\gestor-pecas\.env` com os `GESTOR_TOTVS_*` do modelo `app\deploy\totvs-real.env.example`. Depois, para o Protheus enviar dados ao Gestor, peça o IP de saída dele e coloque em `GESTOR_TOTVS_SOAP_ALLOWED_SOURCE_CIDRS` (ex.: `200.1.2.3/32`).
8. **Desenhos dos operadores**: informe o caminho de rede real em `GESTOR_OPERATOR_DRAWING_ROOTS` no `.env`. A conta do serviço acessa a rede como `NOME-DA-VM$`: dê leitura a ela na pasta.
9. **Telegram**: já nasce ligado na VM. É o mesmo bot do notebook, então o Telegram do notebook precisa estar desligado (quem usa o notebook faz isso). Se o bot responder duplicado, é porque os dois estão ligados.
10. **Acesso do notebook de desenvolvimento (botão "Publicar na VM")**: as atualizações são manuais, empurradas do notebook do desenvolvedor por PowerShell Remoting (WinRM). Na VM, como Administrador:
    ```powershell
    Enable-PSRemoting -Force
    Set-NetFirewallRule -Name "WINRM-HTTP-In-TCP" -RemoteAddress IP.DO.NOTEBOOK   # só o notebook entra
    ```
    No notebook (se ele não estiver no mesmo domínio da VM), como Administrador: `Set-Item WSMan:\localhost\Client\TrustedHosts -Value gestor-peca`. Teste: `Enter-PSSession gestor-peca -Credential (Get-Credential)`. Nada fica rodando na VM esperando ordem: ela só é alterada quando o desenvolvedor clica no botão e digita a conta de Administrador.
11. **Monitoramento**: alertas de disco > 80%, memória > 90%, e serviços `gestor-pecas`, `nginx` e PostgreSQL parados.

Depois de editar o `.env`: `Restart-Service gestor-pecas`.

Comandos úteis:

```powershell
Get-Service gestor-pecas, nginx, postgresql*   # estado
Restart-Service gestor-pecas                    # reiniciar o sistema
curl.exe -k https://localhost/api/v1/system/ready   # deve responder 200
```

Documentação completa: `app\deploy\LEIA-ME.md` e `app\docs\REQUISITOS_INFRAESTRUTURA_VM.md`.
