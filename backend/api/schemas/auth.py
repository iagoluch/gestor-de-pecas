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
    #: Entrou com a senha padrão numa conta de gestão: a tela pede uma nova
    #: senha e a API recusa as demais rotas até ela ser definida.
    password_change_required: bool = False
