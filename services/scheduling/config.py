import json
import os
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from zoneinfo import ZoneInfo


class CalendarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret: str = Field(min_length=32)
    roles: list[str] = Field(min_length=1)
    editor_roles: list[str] = Field(default_factory=list)
    mode: str = Field(pattern="^(demo|google)$")
    calendar_id: str = Field(min_length=3, max_length=250)
    timezone: str
    duration_minutes: int = Field(ge=15, le=120)
    lead_minutes: int = Field(ge=0, le=10080)
    horizon_days: int = Field(ge=1, le=90)
    hours: dict[str, list[tuple[str, str]]]
    title: str = Field(min_length=2, max_length=120)
    create_meet: bool = False
    send_invites: bool = False
    token_file: str | None = None

    @model_validator(mode="after")
    def validate_calendar(self):
        from datetime import time
        ZoneInfo(self.timezone)
        for weekday, windows in self.hours.items():
            if weekday not in [str(i) for i in range(7)]:
                raise ValueError("Dia inválido")
            previous = None
            for start, end in windows:
                a, b = time.fromisoformat(start), time.fromisoformat(end)
                if a.tzinfo or b.tzinfo or a >= b or (previous and a < previous):
                    raise ValueError("Faixa de horário inválida")
                previous = b
        if self.mode == "google" and not self.token_file:
            raise ValueError("Autorização Google necessária")
        return self

    @property
    def scope(self):
        # Shared calendar must share conflict protection even across tenant bindings.
        return self.mode + ":" + self.calendar_id.lower()


def settings():
    file = Path(os.environ["LUMI_SCHEDULING_CONFIG"])
    raw = json.loads(file.read_text(encoding="utf-8-sig"))
    return {tenant: CalendarConfig.model_validate(value) for tenant, value in raw.items()}
