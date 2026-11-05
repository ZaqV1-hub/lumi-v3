const dashboardDay=d=>d.toLocaleDateString("sv-SE",{timeZone:"America/Sao_Paulo"});
const TODAY=dashboardDay(new Date());Object.assign(ui,{period:"hoje",day:TODAY,from:TODAY,to:TODAY});
function stats(){
 const date=new Date(),iso=dashboardDay;
 let end=iso(date),start=end;
 if(ui.period==="ontem"){date.setDate(date.getDate()-1);start=end=iso(date)}
 else if(ui.period==="7d"||ui.period==="30d"){date.setDate(date.getDate()-(ui.period==="7d"?6:29));start=iso(date)}
 else if(ui.period==="dia"){start=end=ui.day}
 else if(ui.period==="custom"){start=ui.from;end=ui.to}
 const inPeriod=value=>{if(!value)return false;const day=iso(new Date(value));return day>=start&&day<=end};
 const incoming=c=>c.messages.filter(m=>m.sender==="cliente"&&inPeriod(m.created_at));
 const list=convos.filter(c=>incoming(c).length>0);
 const count=list.reduce((total,c)=>total+incoming(c).length,0);
 const opened=convos.filter(c=>inPeriod(c.created_at)).length;
 return {att:list.length,opened,total:convos.length,msg:count,pa:0,pm:0,vs:"Dados reais do período",wa:list.filter(c=>c.channel==="simulator").length,ig:list.filter(c=>c.channel==="whatsapp").length,instagram:list.filter(c=>c.channel==="instagram").length,comments:list.filter(c=>c.channel==="instagram_comment").length,topics:[["Lumi ativa",list.filter(c=>c.status==="lumi").length],["Aguardando atendimento",list.filter(c=>c.status==="aguardando").length],["Atendimento humano",list.filter(c=>c.status==="humano").length]]};
}
const PERIODS=[["hoje","Hoje"],["ontem","Ontem"],["7d","Últimos 7 dias"],["30d","Últimos 30 dias"],["dia","Dia específico"],["custom","Período personalizado"]];
function subtitle(){
  let tail=PERIODS.find(x=>x[0]===ui.period)[1];
  if(ui.period==="dia")tail+=" · "+fmtBR(ui.day);
  if(ui.period==="custom")tail+=" · "+fmtBR(ui.from)+" a "+fmtBR(ui.to);
  return "Resumo da Lumi de "+me.tenant+" · "+tail;
}
function renderDash(){
  $("#content").innerHTML=`<div class="wrap">
    <div class="hello"><h2>Olá, ${esc(me.name)}</h2><p id="dSub"></p></div>
    <section class="card period" id="period"></section>
    <div class="stack" id="dStats"></div>
    <section class="card">
      <div class="card-h"><h2>Últimos atendimentos</h2><a class="link" href="#conversas" data-reset>Ver todos →</a></div>
      <div class="card-b recent">
        ${convos.slice(0,4).map(c=>`<a href="#conversas" data-open="${c.id}"><span class="ini">${esc(c.name.slice(0,2).toUpperCase())}</span><div style="min-width:0"><div class="r-name">${esc(c.name)} <span>· ${c.channel==="whatsapp"?"WhatsApp":c.channel==="instagram"?"Instagram":c.channel==="instagram_comment"?"Comentário Instagram":"Simulador"}</span></div><div class="r-msg">Lumi: ${esc(c.messages.at(-1)?.content||"Conversa iniciada")}</div></div><span class="r-time num">${new Date(c.messages.at(-1)?.created_at||c.created_at).toLocaleTimeString("pt-BR",{timeZone:"America/Sao_Paulo",hour:"2-digit",minute:"2-digit"})}</span></a>`).join("")}
      </div>
    </section>
  </div>`;
  drawPeriod();drawStats();
  $("#content").querySelectorAll("[data-open]").forEach(a=>a.onclick=()=>{ui.conv=a.dataset.open;ui.session=0;ui.tp="";ui.ch="";ui.q="";ui.mobileDetail=true});
  $("#content").querySelectorAll("[data-reset]").forEach(a=>a.onclick=()=>{ui.tp="";ui.ch="";ui.q="";ui.mobileDetail=false});
}
function drawPeriod(){
  const el=$("#period");
  el.innerHTML=`<div class="chips">${PERIODS.map(([k,l])=>`<button class="chip lg" data-p="${k}" aria-pressed="${ui.period===k}">${l}</button>`).join("")}</div>
  ${ui.period==="dia"?`<div class="range"><label for="dDay">Dia</label><input class="input date" type="date" id="dDay" value="${ui.day}" max="${TODAY}"></div>`:""}
  ${ui.period==="custom"?`<div class="range"><label for="dFrom">De</label><input class="input date" type="date" id="dFrom" value="${ui.from}" max="${TODAY}"><label for="dTo">até</label><input class="input date" type="date" id="dTo" value="${ui.to}" max="${TODAY}"></div>`:""}`;
  el.querySelectorAll("[data-p]").forEach(b=>b.onclick=()=>{ui.period=b.dataset.p;drawPeriod();drawStats();const n=el.querySelector('[data-p="'+ui.period+'"]');if(n)n.focus()});
  const dd=$("#dDay");if(dd)dd.onchange=e=>{if(e.target.value){ui.day=e.target.value;drawStats()}};
  const df=$("#dFrom"),dt=$("#dTo");
  if(df)df.onchange=e=>{if(!e.target.value)return;ui.from=e.target.value;if(ui.to<ui.from){ui.to=ui.from;dt.value=ui.to}drawStats()};
  if(dt)dt.onchange=e=>{if(!e.target.value)return;ui.to=e.target.value;if(ui.from>ui.to){ui.from=ui.to;df.value=ui.from}drawStats()};
}
function drawStats(){
  const s=stats(),pct=v=>s.att?Math.round(v/s.att*100):0;
  $("#dSub").textContent=subtitle();
  $("#dStats").innerHTML=`
    <div class="kpis">
      <div class="card kpi"><span class="k-l">Atendimentos</span><span class="k-v num">${nf(s.att)}</span><span class="k-d">${s.vs}</span><span class="k-n">Conversas com mensagens de clientes no período</span></div>
      <div class="card kpi"><span class="k-l">Mensagens recebidas pela Lumi <button class="info" type="button" aria-label="Como esse número é contado">i<span class="tip" role="tooltip">Conta só as mensagens enviadas pelos clientes. As respostas da Lumi não entram.</span></button></span><span class="k-v num">${nf(s.msg)}</span><span class="k-d">${s.vs}</span><span class="k-n">Somente mensagens dos usuários</span></div>
      <div class="card kpi"><span class="k-l">Atendimentos por canal</span>
        <div class="chan">
          <div><div class="c-row"><span><i class="dot" style="background:var(--teal)"></i>Simulador</span><b class="num">${nf(s.wa)}</b></div><div class="bar teal"><i style="width:${pct(s.wa)}%"></i></div></div>
          <div><div class="c-row"><span><i class="dot" style="background:var(--pink)"></i>WhatsApp</span><b class="num">${nf(s.ig)}</b></div><div class="bar pink"><i style="width:${pct(s.ig)}%"></i></div></div>
          <div><div class="c-row"><span>Instagram</span><b class="num">${nf(s.instagram)}</b></div><div class="bar"><i style="width:${pct(s.instagram)}%"></i></div></div>
          ${s.comments?`<div><div class="c-row"><span>Comentários Instagram</span><b class="num">${nf(s.comments)}</b></div><div class="bar"><i style="width:${pct(s.comments)}%"></i></div></div>`:""}
        </div></div>
    </div>
    <section class="card dash-volume" aria-label="Histórico de atendimentos">
      <div><span class="k-l">Novos atendimentos</span><strong class="num">${nf(s.opened)}</strong><span class="k-n">Conversas abertas no período selecionado</span></div>
      <div><span class="k-l">Conversas armazenadas</span><strong class="num">${nf(s.total)}</strong><span class="k-n">Histórico completo desta empresa, em todos os períodos</span></div>
    </section>
    <div class="dash-grid">
      <section class="card">
        <div class="card-h"><div class="hh"><h2>Situação dos atendimentos</h2><span class="meta">Clique para ver as conversas</span></div></div>
        <div class="card-b topics">${s.topics.map(([n,v])=>`<a class="topic" href="#conversas" data-t="${esc(n)}"><div class="t-row"><span class="t-name">${n}</span><span class="t-val num">${nf(v)}<b>${pct(v)}%</b></span></div><div class="bar"><i style="width:${pct(v)}%"></i></div></a>`).join("")}</div>
      </section>
      <section class="card">
        <div class="card-h"><h2>Acesso rápido</h2></div>
        <div class="card-b shortcuts">
          <a class="shortcut" href="#conversas" data-reset><span class="dot" style="background:var(--violet)"></span>Ver conversas${chev}</a>
          <a class="shortcut" href="#configuracoes" data-tab="instrucoes"><span class="dot" style="background:var(--teal)"></span>Editar instruções da Lumi${chev}</a>
          <a class="shortcut" href="#configuracoes" data-tab="kb"><span class="dot" style="background:var(--gold)"></span>Base de conhecimento${chev}</a>
          <a class="shortcut" href="#configuracoes" data-tab="imgs"><span class="dot" style="background:var(--pink)"></span>Imagens da Lumi${chev}</a>
        </div>
      </section>
    </div>`;
  $("#dStats").insertAdjacentHTML("beforeend", '<a class="btn btn-primary" target="_blank" href="/chat/'+encodeURIComponent(me.slug)+(me.role==='brevia'?'?tenant='+me.tenant_id:'')+'">Abrir simulador do cliente</a>'); const box=$("#dStats");
  box.querySelectorAll("[data-t]").forEach(a=>a.onclick=()=>{ui.tp=a.dataset.t;ui.ch="";ui.q="";ui.mobileDetail=false});
  box.querySelectorAll("[data-reset]").forEach(a=>a.onclick=()=>{ui.tp="";ui.ch="";ui.q="";ui.mobileDetail=false});
  box.querySelectorAll("[data-tab]").forEach(a=>a.onclick=()=>{ui.tab=a.dataset.tab});
}
