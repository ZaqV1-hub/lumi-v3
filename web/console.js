const $=selector=>document.querySelector(selector);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const usd=value=>value==null?'Sem medição':new Intl.NumberFormat('pt-BR',{style:'currency',currency:'USD',maximumFractionDigits:4}).format(value);
const integer=value=>Number(value||0).toLocaleString('pt-BR');
const date=value=>value?new Date(value).toLocaleString('pt-BR'):'Não registrado';
let operator=null,DATA=null,ISSUES=[],period='7d',routeVersion=0;
async function api(path,method='GET',body){
  const response=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();if(method!=='GET')dataLoadedAt=0;if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Confira os campos informados.');return data;
}
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,4500);}
function show(screen){for(const id of ['login','app'])$('#'+id).hidden=id!==screen;}
function modal(html){
  const overlay=$('#overlay');overlay.innerHTML='<div class="modal" role="dialog" aria-modal="true">'+html+'</div>';overlay.hidden=false;
  const close=()=>{overlay.hidden=true;overlay.replaceChildren();};overlay.onclick=e=>{if(e.target===overlay)close();};
  overlay.querySelector('button,input,select')?.focus();return close;
}
document.addEventListener('keydown',event=>{if(event.key==='Escape'){$('#overlay').hidden=true;$('#overlay').replaceChildren();}});
window.addEventListener('unhandledrejection',event=>{event.preventDefault();toast(event.reason?.message||'Não foi possível concluir.');});
$('#pwT').onclick=()=>{const input=$('#pw');input.type=input.type==='password'?'text':'password';$('#pwT').textContent=input.type==='password'?'Mostrar':'Ocultar';};
$('#menuBtn').onclick=()=>document.body.classList.add('nav-open');$('#scrim').onclick=()=>document.body.classList.remove('nav-open');
$('#logout').onclick=async()=>{await api('/api/logout','POST');location.assign('/admin');};
$('#loginForm').onsubmit=async event=>{
  event.preventDefault();const button=event.submitter;button.disabled=true;$('#lErr').hidden=true;
  try{await api('/api/login','POST',{email:$('#em').value,password:$('#pw').value,remember:$('#keep').checked});$('#currentPw').value=$('#pw').value;$('#pw').value='';await boot();}
  catch(error){$('#lErr').textContent=error.message;$('#lErr').hidden=false;}finally{button.disabled=false;}
};
$('#pwForm').onsubmit=async event=>{
  event.preventDefault();$('#pErr').hidden=true;
  if($('#np').value!==$('#np2').value){$('#pErr').textContent='As senhas precisam ser iguais.';$('#pErr').hidden=false;return;}
  const button=event.submitter;button.disabled=true;
  try{await api('/api/password','POST',{current_password:$('#currentPw').value,password:$('#np').value});$('#pwForm').reset();await boot();}
  catch(error){$('#pErr').textContent=error.message;$('#pErr').hidden=false;}finally{button.disabled=false;}
};
async function boot(){
  let me;try{me=await api('/api/me');}catch{show('login');$('#loginForm').hidden=false;$('#pwForm').hidden=true;return;}
  if(me.must_change_password){show('login');$('#loginForm').hidden=true;$('#pwForm').hidden=false;$('#np').focus();return;}
  if(me.role!=='brevia'){location.replace('/admin');return;}
  operator=me;$('#currentPw').value='';$('#meName').textContent=me.name;$('#meAv').textContent=me.name[0];dataLoadedAt=0;await route();
}
function nav(active){
  $('#nav').innerHTML=[['visao','Visão geral','M3 3h6v6H3zM13 3h6v6h-6zM3 13h6v6H3zM13 13h6v6h-6z'],['tenants','Clientes','M3 19V3h12v16M7 7h4M7 11h4M7 15h4M15 9h4v10H3'],['gestao','Projetos e contratos','M3 5h16v14H3zM3 9h16M7 3v4'],['problemas','Problemas','M11 3L1 20h20L11 3zM11 9v5M11 17v1'],['acessos','Acessos','M16 20H4v-3a6 6 0 0112 0v3M15 6a4 4 0 11-8 0 4 4 0 018 0']].map(([id,label,icon])=>'<a href="#/'+id+'" '+(id===active?'aria-current="page"':'')+'><svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="'+icon+'"/></svg>'+label+(id==='problemas'&&DATA.issues?'<span class="badge">'+DATA.issues+'</span>':'')+'</a>').join('');
}
function tenant(id){return DATA.tenants.find(item=>item.id===id);}
function health(item){return '<span class="pill dot '+(item.high_issues?'bad':item.issues?'warn':'ok')+'">'+(item.high_issues?'Problema':item.issues?'Atenção':'Sem alertas')+'</span>';}
function avatar(item){return '<span class="tav" style="background:var(--c'+(DATA.tenants.indexOf(item)%5+1)+')">'+esc(item.name.slice(0,2).toUpperCase())+'</span>';}
function tenantBack(){return '<a class="back console-back" href="/admin#/tenants">Voltar ao console</a>';}
let dataLoadedAt=0;
async function route(){
  if(!operator)return;const version=++routeVersion;document.body.classList.remove('nav-open');
  const parts=(location.hash||'#/visao').replace(/^#\/?/,'').split('/'),page=parts[0];
  try{
    if(!DATA||Date.now()-dataLoadedAt>15000||DATA.period!==period){
      const [issues,data]=await Promise.all([api('/api/console/issues'),api('/api/console/overview?period='+period)]);
      if(version!==routeVersion)return;ISSUES=issues;DATA=data;dataLoadedAt=Date.now();
    }
    show('app');nav(page==='t'?'tenants':page);
    if(page==='t'){
      const item=tenant(parts[1]);if(!item)throw Error('Empresa não encontrada');const tab=parts[2]||'custos';
      if(tab==='painel'){location.assign('/admin?tenant='+item.id+'#dashboard');return;}
      if(tab==='chat'){location.assign('/chat/'+encodeURIComponent(item.slug)+'?tenant='+item.id);return;}
      if(tab==='acessos')await renderAccesses($('#content'),item.id);else await renderCosts($('#content'),item);
    }else if(page==='gestao')await renderBusiness($('#content'),parts[1]);else if(page==='tenants')renderTenants();else if(page==='problemas')renderIssues();else if(page==='acessos')await renderAccesses($('#content'));else renderOverview();
  }catch(error){toast(error.message);}
}
window.addEventListener('hashchange',route);window.addEventListener('DOMContentLoaded',boot);
