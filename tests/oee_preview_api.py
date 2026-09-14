"""Servidor somente leitura para QA visual do OEE no banco local de simulação."""

from dataclasses import replace

from backend.api.config import WebSettings
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from app.database import Database
from app.database.config import load_postgres_config
from scripts.run_simulacao_residencia import configure_environment


configure_environment()
settings = replace(WebSettings.from_env(), ai_enabled=False, ai_api_key="")

app = create_app(
    settings=settings,
    database_factory=lambda: Database(config=load_postgres_config(testing=True)),
)

visual_manager = SessionUser(
    id=0,
    name="Auditoria OEE",
    role="gestor",
    management_access=True,
    andon_access=True,
    operator_access=False,
)
app.dependency_overrides[get_current_user] = lambda: visual_manager
app.dependency_overrides[require_csrf] = lambda: None
