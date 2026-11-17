"""Registro de modelos para provisionamento, sem iniciar aplicação ou seed."""
from sqlalchemy import inspect
from .db import Base
from . import models, media_models, incoming_models, onboarding_models, tool_models
from . import usage_models, console_models, business_models, tenant_runtime
from .whatsapp import models as whatsapp_models
from .whatsapp import calling_models
from .whatsapp import handover_alerts
from .instagram import models as instagram_models, comment_models
from . import role_instructions, tenant_ai, reply_delivery

metadata = Base.metadata


def prepare_feature_call_columns(connection):
    """Preserva chamadas antigas sem data nem mensagem vinculadas."""
    dialect = connection.dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise ValueError("Unsupported migration database")
    columns = {column["name"] for column in inspect(connection).get_columns("feature_calls")}
    if "created_at" not in columns:
        timestamp = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "TIMESTAMP"
        connection.exec_driver_sql("ALTER TABLE feature_calls ADD COLUMN created_at " + timestamp)
    if "message_id" not in columns:
        connection.exec_driver_sql("ALTER TABLE feature_calls ADD COLUMN message_id VARCHAR(36)")
