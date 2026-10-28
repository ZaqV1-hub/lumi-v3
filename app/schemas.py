from pydantic import BaseModel, Field


class Login(BaseModel):
    email: str
    password: str


class TextInput(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class Start(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class Settings(BaseModel):
    identity: str = Field(min_length=1, max_length=10000)
    personality: str = Field(min_length=1, max_length=10000)
    tone: str = Field(default="Neutro", pattern="^(Alegre|Neutro|Formal)$")
    length: str = Field(default="Curto", pattern="^(Curto|Médio|Detalhado)$")
    style: str = Field(default="Objetivo", pattern="^(Objetivo|Explicativo)$")
    max_pending: int = Field(default=3, ge=1, le=10)


class Knowledge(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=20000)
