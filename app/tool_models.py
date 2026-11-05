from datetime import datetime
from sqlalchemy import ForeignKeyConstraint, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class ToolContract(Base):
    __tablename__ = "tool_contracts"
    feature_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    parameters_schema: Mapped[str] = mapped_column(Text)
    secret_env: Mapped[str] = mapped_column(String(120))
    __table_args__ = (ForeignKeyConstraint(["feature_id"], ["tenant_features.id"]),)


class ToolReplyAccess(Base):
    __tablename__ = "tool_reply_access"
    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    feature_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(["message_id"], ["messages.id"]),
        ForeignKeyConstraint(["feature_id"], ["tenant_features.id"]),
    )


class ToolContext(Base):
    __tablename__ = "tool_contexts"
    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    feature_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36))
    result: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]),
        ForeignKeyConstraint(["feature_id"], ["tenant_features.id"]),
    )
