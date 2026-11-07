"""Registro de modelos para provisionamento, sem iniciar aplicação ou seed."""
from .db import Base
from . import models, media_models, incoming_models, onboarding_models, tool_models
from . import usage_models, console_models, business_models, tenant_runtime
from .whatsapp import models as whatsapp_models
from .instagram import models as instagram_models, comment_models
from . import role_instructions, tenant_ai

metadata = Base.metadata
