from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


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
