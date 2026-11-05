let businessData=null,businessTab='projects';
const businessStatus={planejado:'Planejado',em_andamento:'Em andamento',aguardando:'Aguardando',concluido:'Concluído',arquivado:'Arquivado',ativo:'Ativo',encerrado:'Encerrado',cancelado:'Cancelado'};
const hours=minutes=>(Number(minutes||0)/60).toLocaleString('pt-BR',{maximumFractionDigits:2})+' h';
const brDate=value=>value?value.split('-').reverse().join('/'):'Não informado';
const brMoney=value=>value==null?'Não informado':new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(value/100);
const bizPath=()=>'/api/console/business/clients/'+businessData.id;
function businessEmpty(text){return '<div class="empty">'+esc(text)+'</div>';}
function bizSource(kind,id){const ref=businessData.sources?.find(s=>s.kind===kind&&s.record_id===id);return ref?'<a class="console-link" href="'+esc(ref.url)+'" target="_blank" rel="noopener noreferrer">Fonte no Notion</a>':'';}
function bizActions(id,kind,label='Editar'){return '<button class="btn btn-ghost btn-sm" data-biz-edit="'+kind+'" data-id="'+esc(id)+'">'+label+'</button>';}
function bizTable(headers,rows){return '<div class="scroll-table"><table><thead><tr>'+headers.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+rows.join('')+'</tbody></table></div>';}

async function managementChat(){
  const chat=await api('/api/console/business/chat','POST');
  sessionStorage.setItem('lumi-client-'+chat.slug+'-management',chat.token);
  location.assign('/chat/'+encodeURIComponent(chat.slug)+'?tenant='+encodeURIComponent(chat.tenant_id)+'&management=1');
}

async function renderBusiness(target,tid){
  const hash=location.hash;
  if(!tid){
    target.innerHTML='<div class="ph"><div><h1>Projetos e contratos</h1><p>Gestão dos clientes da Brevia.</p></div><button class="btn btn-primary" id="managementChat">Conversar com a Lumi</button></div><div class="tgrid">'+DATA.tenants.map(t=>'<a class="card business-client" href="#/gestao/'+t.id+'"><h2>'+esc(t.name)+'</h2><p>Projetos, contratos, histórico e horas</p><span>Abrir gestão</span></a>').join('')+'</div>';
    $('#managementChat').onclick=managementChat;return;
  }
  const data=await api('/api/console/business/clients/'+encodeURIComponent(tid));
  if(hash!==location.hash)return;
  businessData=data;drawBusiness(target);
}

function drawBusiness(target=$('#content')){
  const d=businessData,active=d.contracts.filter(c=>c.status==='ativo');
  const budget=active.reduce((a,c)=>a+c.included_minutes+c.carried_minutes,0),used=active.reduce((a,c)=>a+c.used_minutes,0);
  target.innerHTML='<div class="business-page"><a class="back console-back" href="#/gestao">Todos os clientes</a><div class="ph"><div><h1>'+esc(d.name)+'</h1><p>Projetos, contratos e manutenção</p></div><div class="business-actions"><a class="btn btn-ghost console-link" href="/admin?tenant='+d.id+'#dashboard">Painel da Lumi</a><button class="btn btn-primary" id="managementChat">Conversar com a Lumi</button></div></div><div class="kpis">'+kpi('Projetos em andamento',d.projects.filter(p=>p.status==='em_andamento').length,'Dados cadastrados pela Brevia')+kpi('Contratos ativos',active.length,'Franquias por contrato')+kpi('Horas contratadas',hours(budget),'Contratos ativos')+kpi('Horas consumidas',hours(used),'Saldo '+hours(budget-used))+'</div><section class="card business-profile"><div><h2>Informações do cliente</h2><p>'+esc(d.profile.contact_name||'Contato ainda não cadastrado')+(d.profile.contact_email?' · '+esc(d.profile.contact_email):'')+'</p></div><button class="btn btn-ghost" id="editBusinessClient">Editar informações</button></section><div class="business-tabs" role="tablist">'+[['projects','Projetos'],['contracts','Contratos'],['work','Horas'],['updates','Histórico']].map(([id,label])=>'<button class="chip" role="tab" data-business-tab="'+id+'" aria-selected="'+(businessTab===id)+'" aria-pressed="'+(businessTab===id)+'">'+label+'</button>').join('')+'</div><section class="card" id="businessBody"></section><p class="hint">Projetos, contratos, atividades e histórico podem ser consultados pelos gestores autorizados deste cliente. As notas internas do cadastro ficam somente com a Brevia.</p></div>';
  $('#managementChat').onclick=managementChat;$('#editBusinessClient').onclick=()=>businessForm('client',d.profile);
  document.querySelectorAll('[data-business-tab]').forEach(b=>b.onclick=()=>{businessTab=b.dataset.businessTab;drawBusiness();});
  drawBusinessTab();
}

function drawBusinessTab(){
  const d=businessData,host=$('#businessBody');let content='';
  if(businessTab==='projects'){
    content='<div class="card-h"><div><h2>Projetos</h2><p>Andamento, próximos passos e prazo.</p></div><button class="btn btn-primary" data-new-business="project">Novo projeto</button></div><div class="business-projects">'+d.projects.map(p=>'<article class="business-project"><div class="business-actions"><h3>'+esc(p.name)+'</h3><span class="pill '+(p.status==='concluido'?'ok':'off')+'">'+esc(businessStatus[p.status])+'</span></div><p class="business-text">'+esc(p.summary||'Resumo ainda não cadastrado.')+'</p><p class="business-text"><b>Próximos passos</b><br>'+esc(p.next_steps||'Não informado')+'</p><small>Prazo: '+brDate(p.due_date)+'</small><div class="business-actions">'+bizActions(p.id,'project')+bizActions(p.id,'update','Registrar andamento')+bizSource('project',p.id)+'</div></article>').join('')+'</div>';
    if(!d.projects.length)content+=businessEmpty('Cadastre o primeiro projeto deste cliente.');
  }else if(businessTab==='contracts'){
    content='<div class="card-h"><div><h2>Contratos</h2><p>As horas pertencem ao contrato e não são renovadas automaticamente.</p></div><button class="btn btn-primary" data-new-business="contract" '+(!d.projects.length?'disabled':'')+'>Novo contrato</button></div>';
    content+=d.contracts.length?'<div class="business-contracts">'+d.contracts.map(c=>'<article class="business-contract"><header><div><small>'+esc(d.projects.find(p=>p.id===c.project_id)?.name||'')+'</small><h3>'+esc(c.title)+'</h3></div><span class="pill '+(c.status==='ativo'?'ok':'off')+'">'+esc(businessStatus[c.status])+'</span></header><p class="business-text">'+esc(c.description||c.kind)+'</p><dl><div><dt>Tipo</dt><dd>'+esc(c.kind)+'</dd></div><div><dt>Vigência</dt><dd>'+brDate(c.start_date)+' a '+brDate(c.end_date)+'</dd></div><div><dt>Horas consumidas</dt><dd>'+hours(c.used_minutes)+' de '+hours(c.included_minutes+c.carried_minutes)+'</dd></div><div><dt>Saldo</dt><dd>'+hours(c.remaining_minutes)+'</dd></div><div><dt>Valor do contrato</dt><dd>'+brMoney(c.amount_cents)+'</dd></div></dl><footer>'+bizSource('contract',c.id)+bizActions(c.id,'contract')+'</footer></article>').join('')+'</div>':businessEmpty(d.projects.length?'Nenhum contrato cadastrado.':'Cadastre um projeto antes de adicionar contratos.');
  }else if(businessTab==='work'){
    content='<div class="card-h"><div><h2>Lançamentos de horas</h2><p>Registre o trabalho realizado e o contrato consumido. Saldos históricos importados entram no total do contrato, sem duplicar atividades.</p></div><button class="btn btn-primary" data-new-business="work" '+(!d.contracts.length?'disabled':'')+'>Lançar horas</button></div><div class="card-b business-filters"><label>De<input class="inp" type="date" id="workFrom"></label><label>Até<input class="inp" type="date" id="workTo"></label><label>Contrato<select class="sel" id="workContract"><option value="">Todos</option>'+d.contracts.map(c=>'<option value="'+c.id+'">'+esc(c.title)+'</option>').join('')+'</select></label></div><div id="workRows"></div>';
  }else{
    content='<div class="card-h"><div><h2>Histórico dos projetos</h2><p>Andamentos registrados pela equipe, com data e responsável.</p></div><button class="btn btn-primary" data-new-business="update" '+(!d.projects.length?'disabled':'')+'>Registrar andamento</button></div><div class="card-b">'+(d.updates.map(u=>'<article class="business-update"><small>'+esc(date(u.created_at))+' · '+esc(u.actor)+' · '+esc(d.projects.find(p=>p.id===u.project_id)?.name||'')+'</small><p class="business-text">'+esc(u.content)+'</p></article>').join('')||businessEmpty('Nenhum andamento registrado.'))+'</div>';
  }
  host.innerHTML=content;
  host.querySelectorAll('[data-new-business]').forEach(b=>b.onclick=()=>businessForm(b.dataset.newBusiness));
  host.querySelectorAll('[data-biz-edit]').forEach(b=>b.onclick=()=>{
    const type=b.dataset.bizEdit,rows=type==='project'||type==='update'?d.projects:type==='contract'?d.contracts:d.work_logs;
    businessForm(type,rows.find(row=>row.id===b.dataset.id));
  });
  if(businessTab==='work'){
    ['workFrom','workTo','workContract'].forEach(id=>$('#'+id).onchange=drawWorkRows);drawWorkRows();
  }
}

function drawWorkRows(){
  const from=$('#workFrom').value,to=$('#workTo').value,contract=$('#workContract').value;
  const rows=businessData.work_logs.filter(w=>(!from||w.work_date>=from)&&(!to||w.work_date<=to)&&(!contract||w.contract_id===contract));
  $('#workRows').innerHTML='<p class="business-total">Total de lançamentos detalhados no filtro: <b>'+hours(rows.reduce((a,w)=>a+w.minutes,0))+'</b></p>'+(rows.length?bizTable(['Data','Contrato','Atividade','Tempo','Registrado por',''],rows.map(w=>'<tr><td>'+brDate(w.work_date)+'</td><td>'+esc(businessData.contracts.find(c=>c.id===w.contract_id)?.title||'')+'</td><td class="business-text">'+esc(w.description)+'</td><td>'+hours(w.minutes)+'</td><td>'+esc(w.actor)+'</td><td>'+bizActions(w.id,'work')+'</td></tr>')):businessEmpty('Nenhuma atividade neste filtro.'));
  $('#workRows').querySelectorAll('[data-biz-edit]').forEach(b=>b.onclick=()=>businessForm('work',businessData.work_logs.find(w=>w.id===b.dataset.id)));
}
