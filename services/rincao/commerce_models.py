import re
from datetime import date
from pydantic import BaseModel, ConfigDict, Field, field_validator


def cpf_digits(value):
    value = re.sub(r"\D", "", value)
    if len(value) != 11 or len(set(value)) == 1:
        raise ValueError("cpf_invalido")
    for size in (9, 10):
        digit = (sum(int(n) * (size + 1 - i) for i, n in enumerate(value[:size])) * 10 % 11) % 10
        if digit != int(value[size]):
            raise ValueError("cpf_invalido")
    return value


class Cart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visit_date: date
    ticket_type: str = Field(pattern="^(padrao|promo)$")
    adults: int = Field(ge=0, le=100)
    children: int = Field(ge=0, le=100)
    exempt: int = Field(ge=0, le=100)


class Buyer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: str = Field(min_length=20, max_length=80)
    name: str = Field(min_length=2, max_length=120)
    cpf: str = Field(min_length=11, max_length=14)
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=120)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("nome_invalido")
        return value.strip()

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        if value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("email_invalido")
        return value

    @field_validator("cpf")
    @classmethod
    def validate_cpf(cls, value):
        return cpf_digits(value)


class PurchaseStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: str = Field(min_length=20, max_length=80)
