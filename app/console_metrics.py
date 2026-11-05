"""Agregações do console: valores medidos, em USD; não são faturas do Codex."""
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from .access import console_user
from .db import Session
from .models import Tenant, Message, Conversation, User
from .console_models import ConsoleAccount, ConsoleIssue, ConsoleAudit, RemovedAccess
from .usage_models import ModelCall, ResponseRun
from .whatsapp.models import Channel
from .instagram.models import Channel as InstagramChannel
from .conversations import timestamp
from .tenant_runtime import listed,enabled
from .usage import api_cost

router = APIRouter(prefix="/api/console")
ZONE = ZoneInfo("America/Sao_Paulo")


def local_date(value):
    if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZONE).date()


def aggregate(calls, start, end):
    selected=[row for row in calls if start<=local_date(row.created_at)<end]
    return {"estimated_usd":sum(api_cost(row) or 0 for row in selected),
            "calls":len(selected),"unknown_cost_calls":sum(api_cost(row) is None for row in selected),
            "measured_conversations":len({row.conversation_id for row in selected}),
            "input_tokens":sum(row.input_tokens or 0 for row in selected),
            "output_tokens":sum(row.output_tokens or 0 for row in selected)}


def boundary(day):
    return datetime.combine(day,time.min,tzinfo=ZONE).astimezone(timezone.utc)


@router.get("/overview")
def overview(period: Literal["hoje","7d","30d","mes"]="7d", actor=Depends(console_user)):
    today=datetime.now(ZONE).date(); end=today+timedelta(days=1); month=today.replace(day=1)
    start=month if period=="mes" else end-timedelta(days={"hoje":1,"7d":7,"30d":30}.get(period,7))
    previous=start-(end-start); oldest=min(previous,month)
    with Session() as db:
        tenants=[row for row in db.scalars(select(Tenant).order_by(Tenant.name)) if listed(db,row.id)]
        tids=[row.id for row in tenants]
        calls=list(db.scalars(select(ModelCall).where(ModelCall.created_at>=boundary(oldest),ModelCall.tenant_id.in_(tids))))
        grouped=defaultdict(list)
        for call in calls: grouped[call.tenant_id].append(call)
        messages=dict(db.execute(select(Message.tenant_id,func.count()).where(Message.sender=="cliente",Message.tenant_id.in_(tids),
            Message.created_at>=boundary(start),Message.created_at<boundary(end)).group_by(Message.tenant_id)).all())
        flows=defaultdict(Counter)
        for tid,status,count in db.execute(select(Conversation.tenant_id,Conversation.status,func.count()).where(
                Conversation.tenant_id.in_(tids),Conversation.created_at>=boundary(start),Conversation.created_at<boundary(end)).group_by(Conversation.tenant_id,Conversation.status)):
            flows[tid][status]=count
        issues=Counter(db.scalars(select(ConsoleIssue.tenant_id).where(ConsoleIssue.tenant_id.in_(tids),ConsoleIssue.status!="resolvido")))
        high=Counter(db.scalars(select(ConsoleIssue.tenant_id).where(ConsoleIssue.tenant_id.in_(tids),ConsoleIssue.status!="resolvido",ConsoleIssue.priority=="alta")))
        accounts={row.user_id:row for row in db.scalars(select(ConsoleAccount))}
        removed=set(db.scalars(select(RemovedAccess.user_id)))
        accesses=Counter(user.tenant_id for user in db.scalars(select(User)) if user.id not in removed and (not accounts.get(user.id) or accounts[user.id].role!="brevia"))
        channels=set(db.scalars(select(Channel.tenant_id)))
        instagram=set(db.scalars(select(InstagramChannel.tenant_id)))
        latency=defaultdict(list)
        for tid,ms in db.execute(select(ResponseRun.tenant_id,ResponseRun.duration_ms).join(Message,Message.id==ResponseRun.message_id).where(
                ResponseRun.status=="completed",ResponseRun.tenant_id.in_(tids),Message.created_at>=boundary(start),Message.created_at<boundary(end))):latency[tid].append(ms)
        rows=[]
        for tenant in tenants:
            measured=grouped[tenant.id]; flow=flows[tenant.id]; stats=aggregate(measured,start,end)
            rows.append({"id":tenant.id,"name":tenant.name,"slug":tenant.slug,
                "lumi_enabled":enabled(db,tenant.id),"configured":bool(tenant.identity.strip() and tenant.personality.strip()),
                "channels":["simulator"]+(["whatsapp_configured"] if tenant.id in channels else [])+(["instagram_configured"] if tenant.id in instagram else []),
                **stats,"messages":messages.get(tenant.id,0),"conversations":sum(flow.values()),"flow":dict(flow),
                "month":aggregate(measured,month,end),"today":aggregate(measured,today,end),
                "accesses":accesses[tenant.id],"issues":issues[tenant.id],"high_issues":high[tenant.id],
                "average_response_ms":sum(latency[tenant.id])/len(latency[tenant.id]) if latency[tenant.id] else None})
        days=[]; day=start
        while day<end:
            days.append({"date":day.isoformat(),"tenants":{tenant.id:aggregate(grouped[tenant.id],day,day+timedelta(days=1)) for tenant in tenants}})
            day+=timedelta(days=1)
        return {"period":period,"start":start.isoformat(),"end":today.isoformat(),"tenants":rows,"daily":days,
            "current":aggregate(calls,start,end),"previous":aggregate(calls,previous,start),
            "today":aggregate(calls,today,end),"month":aggregate(calls,month,end),
            "messages":sum(messages.values()),"conversations":sum(sum(flow.values()) for flow in flows.values()),
            "issues":sum(issues.values()),"high_issues":sum(high.values()),"channel_cost_usd":None,
            "note":"Codex local: custo de API zero. O uso de um provider de API passará a ser contabilizado. Assinatura, infraestrutura e canais não incluídos."}


@router.get("/audit")
def audit(tenant: str | None=None, actor=Depends(console_user)):
    with Session() as db:
        query=select(ConsoleAudit,User.name).join(User,User.id==ConsoleAudit.actor_id)
        if tenant:query=query.where(ConsoleAudit.tenant_id==tenant)
        return [{"id":row.id,"actor":name,"tenant_id":row.tenant_id,"action":row.action,"target":row.target,
                 "created_at":timestamp(row.created_at)} for row,name in db.execute(query.order_by(ConsoleAudit.created_at.desc()).limit(100))]
