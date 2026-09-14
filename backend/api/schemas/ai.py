from pydantic import BaseModel, ConfigDict, Field, field_validator

from mes.contracts import MAX_AI_CONVERSATION_TITLE_CHARS, MAX_AI_MESSAGE_CHARS


class AIConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=MAX_AI_CONVERSATION_TITLE_CHARS)

    @field_validator("title")
    @classmethod
    def non_empty_title(cls, value):
        if value is not None and not value.strip():
            raise ValueError("O título não pode ficar vazio.")
        return value


class AIMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=MAX_AI_MESSAGE_CHARS)
    retry: bool = False
