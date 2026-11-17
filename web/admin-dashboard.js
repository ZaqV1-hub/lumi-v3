const dashboardDay=d=>d.toLocaleDateString("sv-SE",{timeZone:"America/Sao_Paulo"});
const TODAY=dashboardDay(new Date());Object.assign(ui,{period:"hoje",day:TODAY,from:TODAY,to:TODAY});
function dashboardPeriod() {
  const today = dashboardDay(new Date());
  const shift = days => {
    const value = new Date(today + 'T12:00:00Z');
    value.setUTCDate(value.getUTCDate() + days);
    return value.toISOString().slice(0, 10);
  };
  if (ui.period === 'ontem') return [shift(-1), shift(-1)];
  if (ui.period === '7d') return [shift(-6), today];
  if (ui.period === '30d') return [shift(-29), today];
  if (ui.period === 'dia') return [ui.day, ui.day];
  if (ui.period === 'custom') return [ui.from, ui.to];
  return [today, today];
}
let dashboardRequest = 0;

const PERIODS=[["hoje","Hoje"],["ontem","Ontem"],["7d","Últimos 7 dias"],["30d","Últimos 30 dias"],["dia","Dia específico"],["custom","Período personalizado"]];
function subtitle(){
  let tail=PERIODS.find(x=>x[0]===ui.period)[1];
  if(ui.period==="dia")tail+=" · "+fmtBR(ui.day);
  if(ui.period==="custom")tail+=" · "+fmtBR(ui.from)+" a "+fmtBR(ui.to);
  return "Resumo da " + assistantName() + " de " + me.tenant+" · "+tail;
}
function renderDash(){
  $("#content").innerHTML=`<div class="wrap">
    <div class="hello"><h2>Olá, ${esc(me.name)}</h2><p id="dSub"></p></div>
    <section class="card period" id="period"></section>
    <div class="stack" id="dStats"></div>
    <section class="card" id="dashboardRecent" hidden></section>
  </div>`;
  drawPeriod();
  void drawStats();
}

function renderRecent(recent) {
  const element = $("#dashboardRecent");
  element.hidden = !recent.length;
  element.innerHTML = `<div class="card-h"><h2>Últimos atendimentos</h2><a class="link" href="#conversas" data-reset>Ver todos →</a></div>
    <div class="card-b recent">${recent.map(c => {
      const last = c.last_message;
      const label = {cliente:c.name,lumi:assistantName(),humano:"Atendente"}[last?.sender];
      return `<a href="#conversas" data-open="${esc(c.id)}"><span class="ini">${esc(c.name.slice(0,2).toUpperCase())}</span><div style="min-width:0"><div class="r-name">${esc(c.name)} <span>· ${conversationChannel(c.channel)}</span></div><div class="r-msg">${label ? esc(label) + ': ' : ''}${esc(last?.content || last?.attachment_name || "Conversa iniciada")}</div></div><span class="r-time num">${clockTime(last?.created_at || c.created_at)}</span></a>`;
    }).join("")}</div>`;
  element.querySelectorAll("[data-open]").forEach(a => a.onclick = () => {
    ui.conv = a.dataset.open; ui.tp = ""; ui.q = ""; ui.mobileDetail = true;
  });
  element.querySelector("[data-reset]").onclick = () => {
    ui.conv = ""; ui.tp = ""; ui.q = ""; ui.mobileDetail = false;
  };
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
async function drawStats() {
  const request = ++dashboardRequest;
  const [start, end] = dashboardPeriod();
  $("#dSub").textContent = subtitle();
  $("#dashboardRecent").hidden = true;
  adminDataStatus($("#dStats"), "Carregando dados do período…");
  try {
    const query = new URLSearchParams({start, end});
    const data = await api("/api/admin/dashboard?" + query, "GET", undefined, AbortSignal.timeout(30000));
    if (request !== dashboardRequest || page() !== "dashboard") return;
    updateHandoverCount(data.waiting_count);
    paintStats(data);
    renderRecent(data.recent);
  } catch {
    if (request === dashboardRequest && page() === "dashboard") {
      adminDataStatus($("#dStats"), "Não foi possível carregar os dados do período.", drawStats);
    }
  }
}

function paintStats(s) {
  const pct = value => s.att ? Math.round(value / s.att * 100) : 0;
  const count = channel => s.channels[channel] || 0;
  const topics = ["lumi", "aguardando", "humano"].map(status => [status, s.statuses[status] || 0]);
  $("#dStats").innerHTML=`
    <div class="kpis">
      <div class="card kpi"><span class="k-l">Atendimentos</span><span class="k-v num">${nf(s.att)}</span><span class="k-d">Dados reais do período</span><span class="k-n">Conversas com mensagens de clientes no período</span></div>
      <div class="card kpi"><span class="k-l">Mensagens recebidas pela ${esc(assistantName())} <button class="info" type="button" aria-label="Como esse número é contado">i<span class="tip" role="tooltip">Conta só as mensagens enviadas pelos clientes. As respostas da ${esc(assistantName())} não entram.</span></button></span><span class="k-v num">${nf(s.msg)}</span><span class="k-d">Dados reais do período</span><span class="k-n">Somente mensagens dos usuários</span></div>
      <div class="card kpi"><span class="k-l">Atendimentos por canal</span>
        <div class="chan">
          <div><div class="c-row"><span><i class="dot" style="background:var(--teal)"></i>Simulador</span><b class="num">${nf(count("simulator"))}</b></div><div class="bar teal"><i style="width:${pct(count("simulator"))}%"></i></div></div>
          <div><div class="c-row"><span><i class="dot" style="background:var(--pink)"></i>WhatsApp</span><b class="num">${nf(count("whatsapp"))}</b></div><div class="bar pink"><i style="width:${pct(count("whatsapp"))}%"></i></div></div>
          <div><div class="c-row"><span>Instagram</span><b class="num">${nf(count("instagram"))}</b></div><div class="bar"><i style="width:${pct(count("instagram"))}%"></i></div></div>
          ${count("instagram_comment")?`<div><div class="c-row"><span>Comentários Instagram</span><b class="num">${nf(count("instagram_comment"))}</b></div><div class="bar"><i style="width:${pct(count("instagram_comment"))}%"></i></div></div>`:""}
        </div></div>
    </div>
    <section class="card dash-volume" aria-label="Histórico de atendimentos">
      <div><span class="k-l">Novos atendimentos</span><strong class="num">${nf(s.opened)}</strong><span class="k-n">Conversas abertas no período selecionado</span></div>
      <div><span class="k-l">Conversas armazenadas</span><strong class="num">${nf(s.total)}</strong><span class="k-n">Histórico completo desta empresa, em todos os períodos</span></div>
    </section>
    <div class="dash-grid">
      <section class="card">
        <div class="card-h"><div class="hh"><h2>Situação dos atendimentos</h2><span class="meta">Clique para ver as conversas</span></div></div>
        <div class="card-b topics">${topics.map(([status,v])=>`<a class="topic" href="#conversas" data-t="${status}"><div class="t-row"><span class="t-name">${esc(statusLabel(status))}</span><span class="t-val num">${nf(v)}<b>${pct(v)}%</b></span></div><div class="bar"><i style="width:${pct(v)}%"></i></div></a>`).join("")}</div>
      </section>
      <section class="card">
        <div class="card-h"><h2>Acesso rápido</h2></div>
        <div class="card-b shortcuts">
          <a class="shortcut" href="#conversas" data-reset><span class="dot" style="background:var(--violet)"></span>Ver conversas${chev}</a>
          <a class="shortcut" href="#configuracoes" data-tab="instrucoes"><span class="dot" style="background:var(--teal)"></span>Editar instruções da ${esc(assistantName())}${chev}</a>
          <a class="shortcut" href="#configuracoes" data-tab="kb"><span class="dot" style="background:var(--gold)"></span>Base de conhecimento${chev}</a>
          <a class="shortcut" href="#configuracoes" data-tab="imgs"><span class="dot" style="background:var(--pink)"></span>Imagens da ${esc(assistantName())}${chev}</a>
        </div>
      </section>
    </div>`;
  $("#dStats").insertAdjacentHTML("beforeend", '<a class="btn btn-primary" target="_blank" href="/chat/'+encodeURIComponent(me.slug)+(me.role==='brevia'?'?tenant='+me.tenant_id:'')+'">Abrir simulador do cliente</a>'); const box=$("#dStats");
  box.querySelectorAll("[data-t]").forEach(a=>a.onclick=()=>{ui.tp=a.dataset.t === 'aguardando' ? 'Aguardando atendimento' : statusLabel(a.dataset.t);ui.conv="";ui.q="";ui.mobileDetail=false});
  box.querySelectorAll("[data-reset]").forEach(a=>a.onclick=()=>{ui.tp="";ui.conv="";ui.q="";ui.mobileDetail=false});
  box.querySelectorAll("[data-tab]").forEach(a=>a.onclick=()=>{ui.tab=a.dataset.tab});
}
