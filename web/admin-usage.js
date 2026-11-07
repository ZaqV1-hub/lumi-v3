const usageToday=()=>new Date().toLocaleDateString('sv-SE',{timeZone:'America/Sao_Paulo'});
function usageShift(day,amount){const date=new Date(day+'T12:00:00Z');date.setUTCDate(date.getUTCDate()+amount);return date.toISOString().slice(0,10);}
let usageFilter={period:'7d',start:usageShift(usageToday(),-6),end:usageToday(),model:''},usageRequest=0,usageData=null;
const usageNumber=value=>value==null?'—':Number(value).toLocaleString('pt-BR');
const usageSeconds=value=>value==null?'—':(value/1000).toLocaleString('pt-BR',{maximumFractionDigits:2})+' s';
const usageMoney=value=>value==null?'—':Number(value).toLocaleString('pt-BR',{style:'currency',currency:'USD',maximumFractionDigits:6});
const usageCost=row=>usageMoney(row.estimated_api_usd)+(row.messages_without_complete_cost?'<small>Parcial · '+row.messages_without_complete_cost+' mensagem(ns) sem custo conhecido</small>':'');
const usageShort=value=>Number(value).toLocaleString('pt-BR',{notation:'compact',maximumFractionDigits:1});
function usageDates(days){return '<div class="usage-dates">'+days.filter((_,i)=>i===0||i===days.length-1||i%Math.max(1,Math.ceil(days.length/5))===0).map(day=>'<span>'+esc(day.date.slice(8)+'/'+day.date.slice(5,7))+'</span>').join('')+'</div>';}
function usageBarChart(days){
  const max=Math.max(...days.map(day=>day.input_tokens+day.output_tokens),1);
  if(!days.some(day=>day.input_tokens+day.output_tokens))return '<div class="usage-empty">Nenhum consumo de tokens registrado no período.</div>';
  return '<div class="usage-axis"><span>Tokens</span><span>'+usageShort(max)+' tokens</span></div><div class="usage-bars">'+days.map(day=>{
    const total=day.input_tokens+day.output_tokens,parts=[Math.max(0,day.input_tokens-day.cached_tokens),day.cached_tokens,day.output_tokens];
    const title=day.date+' · entrada: '+usageNumber(day.input_tokens)+' · cache: '+usageNumber(day.cached_tokens)+' · saída: '+usageNumber(day.output_tokens);
    return '<button class="usage-bar" type="button" title="'+esc(title)+'" aria-label="'+esc(title)+'"><span class="usage-bar-stack" style="height:'+(100*total/max)+'%">'+parts.map((value,index)=>'<i style="height:'+(total?100*value/total:0)+'%;background:var('+['--violet','--teal','--pink'][index]+')"></i>').join('')+'</span></button>';
  }).join('')+'</div>'+usageDates(days);
}
function usageTimeChart(days){
  const values=days.map(day=>day.average_response_ms),max=Math.max(...values.filter(value=>value!=null),1);
  if(!values.some(value=>value!=null))return '<div class="usage-empty">Nenhuma resposta com tempo total medido no período.</div>';
  let path='',connected=false;const points=[];
  values.forEach((value,index)=>{if(value==null){connected=false;return;}const x=days.length===1?300:12+index*576/(days.length-1),y=178-value/max*160;path+=(connected?' L':' M')+x+','+y;connected=true;points.push('<circle cx="'+x+'" cy="'+y+'" r="4" fill="var(--teal)"><title>'+esc(days[index].date+' · '+usageSeconds(value))+'</title></circle>');});
  return '<div class="usage-axis"><span>Tempo de resposta</span><span>'+usageSeconds(max)+'</span></div><svg class="usage-line" viewBox="0 0 600 190" preserveAspectRatio="none" role="img" aria-label="Tempo médio de resposta por dia"><path d="'+path+'" fill="none" stroke="var(--teal)" stroke-width="3" vector-effect="non-scaling-stroke"/>'+points.join('')+'</svg>'+usageDates(days);
}
function usageKpi(label,value,detail){return '<article class="card usage-kpi"><span class="usage-label">'+label+'</span><div class="usage-value">'+value+'</div><p>'+detail+'</p></article>';}
function drawUsage(){
  if(me.role!=='brevia')return;
  $('#content').innerHTML='<div class="usage-report"><div class="usage-intro"><div><h2>Entenda cada resposta da Lumi</h2><p>Consumo, modelos e velocidade de '+esc(me.tenant)+'.</p></div><span class="usage-private">Exclusivo Brevia</span></div><form class="card usage-filters" id="usageFilters"><div class="usage-field"><label for="usagePeriod">Período</label><select id="usagePeriod"><option value="hoje">Hoje</option><option value="7d">Últimos 7 dias</option><option value="30d">Últimos 30 dias</option><option value="custom">Personalizado</option></select></div><div class="usage-field"><label for="usageFrom">De</label><input type="date" id="usageFrom" required></div><div class="usage-field"><label for="usageTo">Até</label><input type="date" id="usageTo" required></div><div class="usage-field"><label for="usageModel">Modelo</label><select id="usageModel"><option value="">Todos os modelos</option></select></div><button type="submit" class="btn btn-primary" id="refreshUsage">Atualizar</button></form><p class="usage-error" id="usageError" role="alert"></p><p class="usage-info" id="usageInfo" role="status"></p><div id="usageBody"><section class="card usage-loading">Carregando o relatório…</section></div></div>';
  $('#usagePeriod').value=usageFilter.period;$('#usageFrom').value=usageFilter.start;$('#usageTo').value=usageFilter.end;
  $('#usageFilters').onsubmit=event=>{event.preventDefault();loadUsage();};
  $('#usagePeriod').onchange=()=>{const period=$('#usagePeriod').value;usageFilter.period=period;if(period==='custom')return;const end=usageToday();$('#usageTo').value=end;$('#usageFrom').value=usageShift(end,period==='hoje'?0:period==='7d'?-6:-29);loadUsage();};
  $('#usageModel').onchange=loadUsage;
  for(const id of ['usageFrom','usageTo'])$('#'+id).oninput=()=>{$('#usagePeriod').value='custom';};
  $("#content").scrollTop=0;
  loadUsage();
}
async function loadUsage(){
  const host=$('#usageBody'),version=++usageRequest;
  usageFilter={period:$('#usagePeriod').value,start:$('#usageFrom').value,end:$('#usageTo').value,model:$('#usageModel').value||usageFilter.model};
  // Uma seleção explícita de todos os modelos limpa o filtro anterior.
  if($('#usageModel').options.length>1)usageFilter.model=$('#usageModel').value;
  const params=new URLSearchParams({start_date:usageFilter.start,end_date:usageFilter.end});if(usageFilter.model)params.set('model',usageFilter.model);
  $('#refreshUsage').disabled=true;$('#usageInfo').textContent='Atualizando medições…';$('#usageError').textContent='';host.setAttribute('aria-busy','true');
  try{
    const data=await api('/api/admin/usage?'+params);
    if(!host.isConnected||version!==usageRequest||page()!=='consumo')return;
    usageData=data;$('#usageModel').innerHTML='<option value="">Todos os modelos</option>'+data.available_models.map(model=>'<option value="'+esc(model)+'">'+esc(model)+'</option>').join('');$('#usageModel').value=usageFilter.model;
    $('#usageInfo').textContent=data.scope+' · '+data.start_date.split('-').reverse().join('/')+' a '+data.end_date.split('-').reverse().join('/');
    renderUsageData(host,data);
  }catch(error){if(host.isConnected&&version===usageRequest){$('#usageError').textContent=error.message;$('#usageInfo').textContent='Não foi possível atualizar o relatório.';}}
  finally{if(host.isConnected&&version===usageRequest){$('#refreshUsage').disabled=false;host.setAttribute('aria-busy','false');}}
}
function renderUsageData(host,data){
  const active=data.configured_model||(data.configured_provider==='demo'?'Demonstração':'Provider de API');
  const cache=data.input_tokens?100*data.cached_tokens/data.input_tokens:0;
  host.innerHTML='<div class="usage-report"><section class="card usage-current"><div><span class="usage-label">Modelo configurado para novas respostas</span><h3>'+esc(active)+'</h3><p>' + (me.lumi_enabled?'O histórico inclui modelos anteriores e a transcrição de áudio.':'A Lumi está desativada neste tenant. O histórico permanece disponível.') + '</p></div><span class="usage-chip">'+esc(data.configured_provider==='codex'?'Codex local':data.configured_provider)+'</span></section><div class="usage-kpis">'+usageKpi('Mensagens medidas',usageNumber(data.messages),usageNumber(data.calls)+' chamadas · '+usageNumber(data.failed_calls)+' com falha')+usageKpi('Tokens processados',usageNumber(data.input_tokens+data.output_tokens),'Entrada '+usageNumber(data.input_tokens)+' · saída '+usageNumber(data.output_tokens))+usageKpi('Tempo médio de resposta',usageSeconds(data.average_response_ms),'95% das respostas em até '+usageSeconds(data.p95_response_ms))+usageKpi('Custo estimado de API',usageMoney(data.estimated_api_usd),data.messages_without_complete_cost?'Total parcial · '+data.messages_without_complete_cost+' mensagem(ns) sem custo conhecido':'Codex local e transcrição local: zero de API')+'</div><div class="usage-charts"><section class="card usage-panel"><h3>Consumo de tokens por dia</h3><p class="usage-caption">Entrada, cache e saída, sem contar o cache duas vezes.</p><div class="usage-legend"><span><i style="background:var(--violet)"></i>Entrada sem cache</span><span><i style="background:var(--teal)"></i>Cache</span><span><i style="background:var(--pink)"></i>Saída</span></div>'+usageBarChart(data.daily)+'<p class="usage-caption">'+cache.toLocaleString('pt-BR',{maximumFractionDigits:1})+'% da entrada reutilizada em cache.</p></section><section class="card usage-panel"><h3>Velocidade das respostas</h3><p class="usage-caption">Média diária do tempo total por mensagem.</p><div class="usage-legend"><span><i style="background:var(--teal)"></i>Tempo médio</span></div>'+usageTimeChart(data.daily)+'<p class="usage-caption">'+esc(data.latency_note)+'</p></section></div><section class="card"><div class="usage-table-head"><div><h3>Consumo por modelo</h3><p class="usage-caption">Comparação dentro do período e modelo selecionados.</p></div><button class="btn btn-ghost btn-sm" id="exportUsage">Baixar resumo CSV</button></div><div class="usage-table-wrap"><table class="usage-table"><thead><tr><th>Modelo</th><th>Chamadas</th><th>Entrada</th><th>Cache</th><th>Saída</th><th>Tempo por chamada</th><th>Custo estimado API</th></tr></thead><tbody>'+data.by_model.map(row=>'<tr><td>'+esc(row.model)+'<small>'+esc(row.kind==='transcricao'?'Transcrição local':row.provider)+'</small></td><td>'+usageNumber(row.calls)+'</td><td>'+usageNumber(row.input_tokens)+'</td><td>'+usageNumber(row.cached_tokens)+'</td><td>'+usageNumber(row.output_tokens)+'</td><td>'+usageSeconds(row.average_call_ms)+'</td><td>'+usageCost(row)+'</td></tr>').join('')+'</tbody></table>'+(data.by_model.length?'':'<div class="usage-table-empty">Nenhuma chamada encontrada para esses filtros.</div>')+'</div></section><section class="card"><div class="usage-table-head"><div><h3>Chamadas recentes</h3><p class="usage-caption">'+esc(data.recent_scope)+'</p></div></div><div class="usage-table-wrap"><table class="usage-table"><thead><tr><th>Data e hora</th><th>Modelo</th><th>Situação</th><th>Entrada / cache / saída</th><th>Tempo da chamada</th><th>Custo estimado API</th></tr></thead><tbody>'+data.recent.map(row=>'<tr><td>'+esc(new Date(row.created_at).toLocaleString('pt-BR'))+'</td><td>'+esc(row.model)+'<small>'+esc(row.provider)+'</small></td><td><span class="usage-status '+(row.status==='completed'?'':'failed')+'">'+(row.status==='completed'?'Concluída':'Falha')+'</span></td><td>'+usageNumber(row.input_tokens)+' / '+usageNumber(row.cached_tokens)+' / '+usageNumber(row.output_tokens)+'</td><td>'+usageSeconds(row.duration_ms)+'</td><td>'+usageMoney(row.estimated_usd)+'</td></tr>').join('')+'</tbody></table>'+(data.recent.length?'':'<div class="usage-table-empty">Nenhuma chamada no período.</div>')+'</div></section><p class="usage-footnote">'+esc(data.note)+' O histórico anterior ao início da medição não está incluído. Mensagens sem custo conhecido: '+data.messages_without_complete_cost+'.</p></div>';
  $('#exportUsage').onclick=exportUsage;
}
function exportUsage(){
  if(!usageData)return;
  const cell=value=>'"'+String(value??'').replace(/^[=+@\-\t\r]/,"'$&").replaceAll('"','""')+'"';
  const rows=[['Início','Fim','Modelo','Provider','Chamadas','Entrada','Cache','Saída','Tempo médio da chamada (ms)','Custo estimado de API (USD)','Mensagens sem custo conhecido'],...usageData.by_model.map(row=>[usageData.start_date,usageData.end_date,row.model,row.provider,row.calls,row.input_tokens,row.cached_tokens,row.output_tokens,row.average_call_ms,row.estimated_api_usd,row.messages_without_complete_cost])];
  const blob=new Blob(['\uFEFF'+rows.map(row=>row.map(cell).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='lumi-'+me.slug+'-consumo-'+usageData.start_date+'-'+usageData.end_date+'.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
