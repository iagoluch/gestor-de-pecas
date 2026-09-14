# Implantação Web

## Desenvolvimento

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --reload
Set-Location web
npm run dev
```

## Build integrado

```powershell
Set-Location web
npm ci
npm run build
Set-Location ..
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

Com `GESTOR_WEB_SERVE_STATIC=true`, o FastAPI entrega `web/dist`; rotas profundas
do React usam o fallback SPA, enquanto a API permanece em `/api/v1`.

## Validação antes de promoção

1. aplicar migrations com espera limitada para locks;
2. validar `/api/v1/system/health` sem expor DSN;
3. validar login, CSRF e restrição setorial;
4. executar a suíte Python e os testes/build do frontend;
5. usar `TEST_DATABASE_URL` isolada para integrações PostgreSQL;
6. testar no posto real leitor/crachá, concorrência, virada de turno, Corte,
   Destaque, Setup, Parada, Retrabalho e finalização parcial;
7. registrar `X-Request-ID`, usuário, recurso, OP/operação e horário em qualquer
   divergência, sem editar eventos históricos.

Rollback de implantação deve trocar a versão Web/servidor, nunca limpar banco ou
reescrever produção.
