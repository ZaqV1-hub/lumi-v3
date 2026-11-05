"""Agregação de metadados de consumo, sem conteúdo de conversas."""
from collections import defaultdict
from datetime import timedelta, timezone
from math import ceil
from statistics import mean
from zoneinfo import ZoneInfo
from .usage import api_cost
from .conversations import timestamp

ZONE=ZoneInfo('America/Sao_Paulo')


def day_of(value):
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(ZONE).date()


def summary(rows):
    costs=defaultdict(float);incomplete=set()
    for row in rows:
        cost=api_cost(row)
        if cost is None:incomplete.add(row.message_id)
        else:costs[row.message_id]+=cost
    complete=[value for mid,value in costs.items() if mid not in incomplete]
    return {'calls':len(rows),'messages':len({row.message_id for row in rows}),
        'input_tokens':sum(row.input_tokens or 0 for row in rows),
        'cached_tokens':sum(row.cached_tokens or 0 for row in rows),
        'output_tokens':sum(row.output_tokens or 0 for row in rows),
        'estimated_api_usd':sum(costs.values()),
        'average_complete_message_usd':mean(complete) if complete else None,
        'messages_without_complete_cost':len(incomplete),
        'failed_calls':sum(row.status!='completed' for row in rows),
        'average_call_ms':mean([row.duration_ms for row in rows if row.status=='completed']) if any(row.status=='completed' for row in rows) else None}


def report(rows,turns,start,end):
    result=summary(rows)
    latencies=sorted(run.duration_ms for run,_ in turns if run.status=='completed')
    result.update(average_response_ms=mean(latencies) if latencies else None,
        p95_response_ms=latencies[ceil(len(latencies)*.95)-1] if latencies else None)
    groups=defaultdict(list);days=defaultdict(list);response_days=defaultdict(list)
    for row in rows:
        groups[(row.provider,row.model)].append(row);days[day_of(row.created_at)].append(row)
    # turns contém tuplas (ResponseRun, data da mensagem original).
    for run,created in turns:
        if run.status=='completed':response_days[day_of(created)].append(run.duration_ms)
    daily=[];day=start
    while day<=end:
        stats=summary(days[day]);stats['date']=day.isoformat()
        stats['average_response_ms']=mean(response_days[day]) if response_days[day] else None
        daily.append(stats);day+=timedelta(days=1)
    result.update(daily=daily,by_model=[{'provider':provider,'model':model,
        'kind':'transcricao' if provider=='faster-whisper-local' else 'conversa',**summary(items)}
        for (provider,model),items in sorted(groups.items())])
    result['recent']=[{'id':row.id,'message_id':row.message_id,'provider':row.provider,'model':row.model,
        'status':row.status,'input_tokens':row.input_tokens,'cached_tokens':row.cached_tokens,
        'output_tokens':row.output_tokens,'duration_ms':row.duration_ms,'audio_seconds':row.audio_seconds,
        'estimated_usd':api_cost(row),'created_at':timestamp(row.created_at)} for row in rows[:50]]
    return result
