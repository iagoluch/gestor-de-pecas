# Plano — nível Desenvolvedor, Admin da fábrica e aba "Apontamento por setor"

Data: 06/11/2026. Status: **planejado, nada construído**. Risco: R3 (auth + permissões + apontamento).

## Decisões do usuário
- Iago = **Desenvolvedor** (controle total). Gabriel Fogaça (`gabriel.fogaca`, Manufatura) = **Admin** (configura o sistema para a linha).
- Admin vê Alterações, Envios ao Protheus e Log do Sistema.
- Admin **não** cria/edita/desativa/apaga contas de admin ou desenvolvedor; só o Desenvolvedor.
- Senha inicial do Gabriel: padrão do projeto (123456), sem troca obrigatória por ora (revisar antes do REAL).
- Nova aba "Apontamento por setor": setor → recurso → tela de apontamento real, sem trocar de login.
- Apontamento do Admin vale de verdade (OEE/Protheus), gravado no nome dele e marcado "feito pela gestão".

## O que existe hoje (verificado)
- `app/core/permissions.py`: `USER_LEVELS`, `USER_MANAGEMENT_LEVELS = ("admin",)`.
- `backend/api/dependencies/auth.py`: `require_admin_user` (`role != "admin"` → 403), usado em management, chamadas, cutting.
- Front: `web/src/config/navigation.ts` (`adminOnly`, `role !== "admin"`), `web/src/App.tsx:85` (`user?.role === "admin"`).
- `backend/api/dependencies/operator.py`: setor e recurso saem do login (`user.role`); o operador gravado é `user.name`.
- Níveis personalizados (`niveis_acesso`, molde de nível-base): usados por `manutencao` e `pcp`.

## Etapa 1 — Nível `desenvolvedor` (backend)
1. Adicionar `desenvolvedor` a `USER_LEVELS`, `MANAGEMENT_WEB_LEVELS`, navegação e abas de consulta (mesmas do admin).
2. Criar `is_admin_or_dev(role)` única em `permissions.py`; `require_admin_user` passa a usar. Criar `require_developer_user`.
3. Varrer TODO `== "admin"` / `role != "admin"` (back e front) e trocar por essa função. Esquecer um = Iago perde acesso.
4. Telas só do Desenvolvedor (hoje: nenhuma além das que o admin já tem; a separação vem da regra 5).
5. Gestão de usuários: admin só enxerga/edita níveis abaixo de admin; `desenvolvedor` e `admin` só pelo Desenvolvedor. Validar no backend (não só esconder no menu). Impedir o admin de promover alguém a admin/dev.
6. Não deixar o último desenvolvedor ser desativado/rebaixado.
7. Migração: criar conta `gabriel.fogaca` (admin) e mudar a conta do Iago para `desenvolvedor`. Só no TEST; backup antes (regra do projeto). REAL só quando o usuário mandar.

## Etapa 2 — Controle do Desenvolvedor sobre o Admin
1. Auditar se toda mudança de configuração do admin grava quem/quando/antes/depois (tela Alterações, migration de auditoria). Listar lacunas (ressalva conhecida: valor cru).
2. Registro de auditoria: só o Desenvolvedor apaga/edita.
3. Desenvolvedor pode desativar a conta do Admin e derrubar a sessão dele.
4. "Desfazer": onde há valor "antes" gravado, oferecer reversão; onde não há, documentar.

## Etapa 3 — Aba "Apontamento por setor"
1. Backend: `sector_for_user`/`validate_resource` aceitam, para admin/dev, um setor informado (parâmetro explícito) e validam que o recurso pertence a ele. Demais níveis seguem como hoje.
2. Gravar `feito_pela_gestao` (ou equivalente) em cada apontamento feito nesse modo; operador gravado = conta do admin/dev. Pode exigir migration (database-engineer).
3. Ver se o envio ao Protheus precisa de tratamento (OP/ operador) quando a origem é gestão — checar `integration-change`.
4. Front: aba (só admin/dev) → lista de setores → recursos → reaproveita as telas existentes (`OperatorPortalPage`, `CuttingPage`, `HighlightPage`, `WorkbenchPage`) recebendo o setor por rota, sem duplicar tela.
5. Faixa fixa "Apontando como <Setor> / <Recurso>" na tela.
6. Limite: respeitar a trava de uma estação ocupada por outro operador (não sobrescrever silenciosamente).

## Etapa 4 — Testes e prova
- Backend: matriz nível × rota (dev, admin, gestor, operador): quem passa/é recusado; admin não edita admin/dev; operador não usa o modo "como setor".
- Regressão: tudo que o admin fazia continua valendo para o desenvolvedor.
- Apontamento por setor: grava marcado, no nome certo, aparece na auditoria.
- Front: menu por nível, rota protegida, faixa.
- Prova visual (regra do usuário): imagens do menu com cada conta e da aba nova. Login com as duas contas no TEST (API 8001).
- Revisão: `qa-test-engineer` + `technical-reviewer` + `application-security-engineer` (R3).

## Ordem sugerida
1 → 2 → 3, cada uma testada e com commit separado. A Etapa 1 sozinha já entrega a separação dev/admin.

## Pontos em aberto
- Nenhum bloqueante. Revisar a senha 123456 antes de levar ao REAL.
