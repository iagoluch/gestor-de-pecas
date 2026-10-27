from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    """Nova senha da conta de gestão que entrou com a senha padrão.

    O tamanho mínimo depende do nível (``app/core/password_policy.py``) e é
    conferido na rota.
    """

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=1, max_length=256)


class SessionUser(BaseModel):
    id: int
    name: str
    role: str
    management_access: bool
    andon_access: bool
    operator_access: bool
    operator_sector: str | None = None
    operator_resources: tuple[str, ...] = ()
    operator_automatic_queue: bool = False
    #: Áreas da fábrica que a conta enxerga na gestão (ver app/core/areas.py).
    areas: list[dict] = []
    #: Setores a que os dados da conta ficam restritos; ``None`` = fábrica toda.
    sector_scope: list[str] | None = None
    #: Áreas cuja fila de prioridades a conta pode ordenar (líder/supervisor).
    queue_areas: list[str] = []
    #: Nível gravado na conta (pode ser personalizado; ``role`` é o efetivo, de
    #: permissões). A trava das sugestões de manutenção lê este campo.
    assigned_level: str | None = None
    #: Pode ver e decidir as sugestões de manutenção (conta Manutenção e admin).
    maintenance_access: bool = False
    #: Entrou com a senha padrão numa conta de gestão: a tela pede uma nova
    #: senha e a API recusa as demais rotas até ela ser definida.
    password_change_required: bool = False
