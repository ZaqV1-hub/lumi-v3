from datetime import date,datetime,time,timedelta,timezone
from fastapi import APIRouter,Depends,HTTPException,Query,Response
from sqlalchemy import select
from .access import current_user
from .conversations import conversation
from .db import Session
from .models import Message
from .usage_models import ModelCall,ResponseRun
from .usage_report import report,ZONE
from .tenant_ai import TenantAI, public_configuration

router=APIRouter()


@router.get('/api/admin/usage')
def usage(response: Response,conversation_id: str | None=None,start_date: date | None=None,end_date: date | None=None,
          model: str | None=Query(default=None,max_length=100),user=Depends(current_user)):
    if user.console_role!='brevia':raise HTTPException(403,'Consumo e velocidade é exclusivo da equipe Brevia')
    response.headers['Cache-Control']='no-store'
    end=end_date or datetime.now(ZONE).date();start=start_date or end-timedelta(days=6)
    if start>end or (end-start).days>365:raise HTTPException(422,'Escolha um período em ordem crescente, de até 366 dias')
    def boundary(day):return datetime.combine(day,time.min,tzinfo=ZONE).astimezone(timezone.utc)
    with Session() as db:
        if conversation_id:conversation(db,user.tenant_id,conversation_id)
        filters=[ModelCall.tenant_id==user.tenant_id]
        if conversation_id:filters.append(ModelCall.conversation_id==conversation_id)
        available=list(db.scalars(select(ModelCall.model).where(*filters).distinct().order_by(ModelCall.model)))
        filters.extend([ModelCall.created_at>=boundary(start),ModelCall.created_at<boundary(end+timedelta(days=1))])
        if model:filters.append(ModelCall.model==model)
        rows=list(db.scalars(select(ModelCall).where(*filters).order_by(ModelCall.created_at.desc(),ModelCall.id.desc())))
        measured=select(ModelCall.message_id).where(*filters)
        dated=list(db.execute(select(ResponseRun,Message.created_at).join(Message,Message.id==ResponseRun.message_id).where(
            ResponseRun.tenant_id==user.tenant_id,ResponseRun.message_id.in_(measured))))
        data=report(rows,dated,start,end)
        config=public_configuration(db.get(TenantAI,user.tenant_id))
        return {**data,'scope':'Todas as chamadas medidas no período selecionado','start_date':start.isoformat(),
            'end_date':end.isoformat(),'models':sorted({row.model for row in rows}),'available_models':available,
            'configured_provider':config['provider'],'configured_model':config['model'] or None,
            'note':'Codex local e transcrição local: custo de API zero. OpenAI API: estimativa em USD pela tarifa Standard e tokens medidos, incluindo gravação de cache quando informada. Não é uma fatura reconciliada; valores incompletos ficam desconhecidos.',
            'latency_note':'Tempo total por mensagem, incluindo fila, transcrição e ferramentas. Com filtro de modelo, considera mensagens que utilizaram esse modelo.',
            'recent_scope':'Até 50 chamadas mais recentes do filtro; os totais e gráficos consideram todo o período.'}
