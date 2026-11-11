"""Generate a tenant's daily report as text using the configured Lumi database."""
import argparse
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from .db import Session
from .models import Conversation, Message, Tenant
from .usage_models import ModelCall
from .usage_report import summary

ZONE = ZoneInfo("America/Sao_Paulo")


def daily_report(db, tenant, day):
    start = datetime.combine(day, time.min, ZONE).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, ZONE).astimezone(timezone.utc)
    messages = (
        Message.tenant_id == tenant.id,
        Message.created_at >= start,
        Message.created_at < end,
    )
    counts = dict(db.execute(select(Message.sender, func.count()).where(*messages)
                             .group_by(Message.sender)).all())
    conversations = db.scalar(select(func.count(func.distinct(Message.conversation_id)))
                              .where(*messages, Message.sender.in_(("cliente", "lumi", "humano"))))
    human = db.scalar(select(func.count(func.distinct(Message.conversation_id)))
                      .where(*messages, Message.sender == "humano"))
    active_human = db.scalar(select(func.count()).select_from(Conversation)
                             .where(Conversation.tenant_id == tenant.id, Conversation.status == "humano"))
    usage = summary(db.scalars(select(ModelCall).where(
        ModelCall.tenant_id == tenant.id, ModelCall.created_at >= start,
        ModelCall.created_at < end)).all())
    cost = usage["estimated_api_usd"]
    return "\n".join([
        f"Resumo diário da Lumi — {tenant.name}",
        f"Dia {day:%d/%m/%Y} (America/Sao_Paulo)",
        f"Gerado em {datetime.now(ZONE):%d/%m/%Y %H:%M}",
        "",
        f"Conversas com mensagens: {conversations}",
        f"Mensagens de clientes: {counts.get('cliente', 0)}",
        f"Mensagens da Lumi: {counts.get('lumi', 0)}",
        f"Mensagens de atendentes: {counts.get('humano', 0)}",
        f"Conversas com resposta humana no dia: {human}",
        f"Conversas atribuídas a humanos no momento da consulta: {active_human}",
        f"Chamadas ao modelo: {usage['calls']}",
        f"Custo estimado de API: {f'US$ {cost:.6f}' if cost is not None else 'indisponível'}",
        f"Mensagens sem custo completo: {usage['messages_without_complete_cost']}",
        "Reservas e conversões: aguardando fonte de contagem por data.",
        "",
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, help="Slug exato do tenant")
    parser.add_argument("--date", type=date.fromisoformat,
                        default=datetime.now(ZONE).date() - timedelta(days=1))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with Session() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant))
        if tenant is None:
            parser.error("Tenant não encontrado neste ambiente.")
        result = daily_report(db, tenant, args.date)
    with args.output.open("x", encoding="utf-8") as file:
        file.write(result)


if __name__ == "__main__":
    main()
