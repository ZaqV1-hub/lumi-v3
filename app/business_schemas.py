from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClientInput(Input):
    contact_name: str = Field(default="", max_length=120)
    contact_email: str = Field(default="", max_length=180)
    notes: str = Field(default="", max_length=20000)


class ProjectInput(Input):
    name: str = Field(min_length=1, max_length=160)
    status: Literal["planejado", "em_andamento", "aguardando", "concluido", "arquivado"] = "em_andamento"
    summary: str = Field(default="", max_length=20000)
    next_steps: str = Field(default="", max_length=10000)
    due_date: date | None = None


class ContractInput(Input):
    project_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=80)
    status: Literal["ativo", "encerrado", "cancelado"] = "ativo"
    description: str = Field(default="", max_length=20000)
    included_minutes: int = Field(default=0, ge=0, le=6000000)
    carried_minutes: int = Field(default=0, ge=0, le=6000000)
    opening_used_minutes: int = Field(default=0, ge=0, le=6000000)
    opening_as_of: date | None = None
    opening_note: str = Field(default="", max_length=10000)
    amount_cents: int | None = Field(default=None, ge=0, le=100000000000)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("O fim do contrato deve ser posterior ao início")
        if self.opening_used_minutes and (not self.opening_as_of or not self.opening_note):
            raise ValueError("Informe a data e a origem do saldo inicial consumido")
        if self.opening_as_of and ((self.start_date and self.opening_as_of < self.start_date) or (self.end_date and self.opening_as_of > self.end_date)):
            raise ValueError("A data do saldo inicial deve estar na vigência do contrato")
        return self


class WorkInput(Input):
    contract_id: str = Field(min_length=1, max_length=36)
    work_date: date
    minutes: int = Field(ge=1, le=1440)
    description: str = Field(min_length=1, max_length=10000)


class UpdateInput(Input):
    content: str = Field(min_length=1, max_length=10000)
