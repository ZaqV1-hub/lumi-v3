async function drawAttendance() {
 const host=document.querySelector('#cfgBody');
 adminDataStatus(host,'Carregando regras de atendimento…');
 let data;
 try{data=await api('/api/admin/attendance');}
 catch{if(host.isConnected&&ui.tab==='attendance')adminDataStatus(host,'Não foi possível carregar as regras.',drawAttendance);return;}
 if(!host.isConnected||ui.tab!=='attendance')return;
 host.innerHTML=attendanceMarkup();
 const $=(s,r=host)=>r.querySelector(s),$$=(s,r=host)=>[...r.querySelectorAll(s)];
 if(![...$('#tz').options].some(option=>option.value===data.timezone))$('#tz').add(new Option(data.timezone,data.timezone));
const clone=o=>JSON.parse(JSON.stringify(o));
const ORDER=[1,2,3,4,5,6,0];
const NAME={0:"Domingo",1:"Segunda-feira",2:"Terça-feira",3:"Quarta-feira",4:"Quinta-feira",5:"Sexta-feira",6:"Sábado"};
const AB={0:"dom",1:"seg",2:"ter",3:"qua",4:"qui",5:"sex",6:"sáb"};
const LOW={0:"domingo",1:"segunda-feira",2:"terça-feira",3:"quarta-feira",4:"quinta-feira",5:"sexta-feira",6:"sábado"};
const D=(on,s,e)=>({on,s,e});
const fromPolicy = p => ({team:p.hours_enabled,tz:p.timezone,alert:p.timeout_enabled,wait:String(p.timeout_minutes),mode:p.timeout_mode==='waiting'?'waiting':'always',phone:p.phone_visibility||(p.phone_consent?'consent':'hidden'),
 days:Object.fromEntries(ORDER.map(d=>{const w=p.windows.find(x=>x.weekday===(d+6)%7);return[d,w?D(w.enabled!==false,w.start,w.end):D(false,'08:00','18:00')]}))});
let saved=fromPolicy(data),st=clone(saved),legacyClaimed=data.timeout_mode==='claimed',saving=false;
const rx=/^([01]\d|2[0-3]):[0-5]\d$/;
const okT=(t,end)=>rx.test(t)||(end&&t==="24:00");
const toMin=t=>{const[h,m]=t.split(":").map(Number);return h*60+m};
const fmtLen=m=>{const h=Math.floor(m/60),r=m%60;return r?`${h} h ${r}`:`${h} h`};
function dayErr(d){const x=st.days[d];if(!x.on)return"";if(!okT(x.s,false))return"Use o formato 09:00 no início.";if(!okT(x.e,true))return"Use o formato 17:00 no fim.";if(toMin(x.e)<=toMin(x.s))return"O fim precisa ser depois do início.";return""}
const noDays=()=>st.team&&!ORDER.some(d=>st.days[d].on);
const waitNum=()=>/^\d{1,3}$/.test(st.wait)?+st.wait:NaN;
const waitErr=()=>{if(!st.alert)return"";const n=waitNum();return(n>=1&&n<=120)?"":"Informe de 1 a 120 minutos."};
const hasErr=()=>(st.team&&(ORDER.some(d=>dayErr(d))||noDays()))||!!waitErr();
const dirty=()=>JSON.stringify(st)!==JSON.stringify(saved);

/* grade semanal */
function buildSched(){
  const ticks=[0,6,12,18,24].map(h=>`<span style="left:${h/24*100}%">${h}h</span>`).join("");
  $("#sched").innerHTML=`<div class="sched-h" aria-hidden="true"><span>Dia</span><span>Horário</span><div class="ticks">${ticks}</div><span></span></div>`+
  ORDER.map(d=>`<div class="day-row" data-d="${d}" data-on="true">
    <div class="d-name"><button class="sw sm" type="button" role="switch" aria-checked="true" aria-label="Atender na ${LOW[d]}"><i></i></button><span>${NAME[d]}</span></div>
    <div class="d-times"><span>Das</span><input class="tm" data-k="s" inputmode="numeric" maxlength="5" autocomplete="off" aria-label="${NAME[d]}, início"><span>até</span><input class="tm" data-k="e" inputmode="numeric" maxlength="5" autocomplete="off" aria-label="${NAME[d]}, fim"></div>
    <div class="d-bar" aria-hidden="true"><i></i></div>
    <div class="d-len num"></div>
    <div class="d-err" role="alert" hidden></div></div>`).join("");
}
function paintDay(d){
  const r=$(`.day-row[data-d="${d}"]`),x=st.days[d],err=dayErr(d);
  r.dataset.on=!!x.on;$(".sw",r).setAttribute("aria-checked",!!x.on);
  $$(".tm",r).forEach(i=>{const k=i.dataset.k;i.disabled=!x.on;if(document.activeElement!==i)i.value=x[k];i.classList.toggle("bad",!!x.on&&((k==="s"&&!okT(x.s,false))||(k==="e"&&!okT(x.e,true))||(!!err&&err.startsWith("O fim")&&k==="e")))});
  const bar=$(".d-bar i",r),len=$(".d-len",r);
  if(x.on&&!err){const a=toMin(x.s),b=toMin(x.e);bar.style.left=a/14.4+"%";bar.style.width=(b-a)/14.4+"%";bar.hidden=false;len.textContent=fmtLen(b-a)}
  else{bar.hidden=true;len.textContent=x.on?"":"Fechado"}
  const e=$(".d-err",r);e.hidden=!err;e.textContent=err;
}
function paintSummary(){
  const el=$("#summary");
  if(noDays()||ORDER.some(d=>dayErr(d))){el.innerHTML=`<div><b>Resumo</b><span>Complete os horários acima.</span></div>`;return}
  const runs=[];
  ORDER.forEach(d=>{const x=st.days[d],key=x.on?x.s+"-"+x.e:"off",l=runs[runs.length-1];if(l&&l.key===key)l.days.push(d);else runs.push({key,days:[d],x})});
  const nm=a=>{const c=a.map(d=>AB[d]);const cap=s=>s[0].toUpperCase()+s.slice(1);return a.length===1?cap(c[0]):a.length===2?`${cap(c[0])} e ${c[1]}`:`${cap(c[0])} a ${c[c.length-1]}`};
  el.innerHTML=runs.map(r=>`<div><b>${nm(r.days)}</b><span class="num">${r.key==="off"?"Fechado":`${r.x.s} às ${r.x.e}`}</span></div>`).join("");
}

/* agora */
function nowIn(tz){
  const p=new Intl.DateTimeFormat("en-US",{timeZone:tz,weekday:"short",hour:"2-digit",minute:"2-digit",hour12:false}).formatToParts(new Date());
  const g=t=>p.find(x=>x.type===t).value;
  const dow={Sun:0,Mon:1,Tue:2,Wed:3,Thu:4,Fri:5,Sat:6}[g("weekday")];
  return{dow,min:(+g("hour")%24)*60+ +g("minute"),txt:`${String(+g("hour")%24).padStart(2,"0")}:${g("minute")}`};
}
function paintNow(){
  const el=$("#now"),t=$("#nowT"),d=$("#nowD"),c=$("#nowC");
  el.classList.remove("open","closed");
  if(!st.team){t.textContent="Sem horário definido";d.textContent="A equipe é considerada disponível o tempo todo.";c.textContent="";return}
  if(hasErr()&&(noDays()||ORDER.some(x=>dayErr(x)))){t.textContent="Horário incompleto";d.textContent="Corrija os campos para ver o status.";c.textContent="";return}
  const n=nowIn(st.tz),x=st.days[n.dow];
  c.textContent=`Agora: ${AB[n.dow]} ${n.txt}`;
  if(x.on&&n.min>=toMin(x.s)&&n.min<toMin(x.e)){el.classList.add("open");t.textContent="Equipe em horário de atendimento";d.textContent=`Atende até ${x.e === "24:00"?"meia-noite":x.e} hoje.`;return}
  el.classList.add("closed");t.textContent="Fora do horário de atendimento";
  for(let o=0;o<=7;o++){const dd=(n.dow+o)%7,y=st.days[dd];if(!y.on)continue;if(o===0&&n.min>=toMin(y.s))continue;
    d.textContent=`A assistente segue atendendo. Próxima abertura: ${o===0?"hoje":o===1?"amanhã":LOW[dd]} às ${y.s}.`;return}
  d.textContent="A assistente segue atendendo.";
}

/* espera */
const WCH=[5,10,15,30,60];
function paintWait(){
  const inp=$("#wait");if(document.activeElement!==inp)inp.value=st.wait;
  $("#waitChips").innerHTML=WCH.map(n=>`<button class="chip" type="button" data-w="${n}" aria-pressed="${waitNum()===n}">${n} min</button>`).join("");
  const e=waitErr();$("#waitErr").textContent=e;$("#waitErr").style.color=e?"var(--pink)":"";
  const n=waitNum();$("#fMin").textContent=n>=1?`${n} ${n===1?"minuto":"minutos"}`:"…";
  $$("#modes .rc").forEach(l=>{const on=l.dataset.m===st.mode;l.classList.toggle("on",on);$("input",l).checked=on});
}

function paintAll(){
  $("#swTeam").setAttribute("aria-checked",st.team);$("#cardTeam").classList.toggle("off",!st.team);
  $("#tz").value=st.tz;
  ORDER.forEach(paintDay);
  $("#warnDays").hidden=!noDays();
  paintSummary();paintNow();
  $("#swWait").setAttribute("aria-checked",st.alert);$("#cardWait").classList.toggle("off",!st.alert);
  paintWait();
  $("#swPhone").setAttribute("aria-checked",st.phone==='visible');
  $("#swPhone").disabled=me.role!=='brevia';
  $("#phoneMode").textContent=st.phone==='consent'?'Modo anterior: autorização por mensagem.':st.phone==='visible'?'O telefone aparece diretamente no perfil, sem pedir autorização no chat.':'O telefone fica oculto no admin, inclusive em conversas antigas.';
  $$('#teamBody button, #teamBody input, #teamBody select').forEach(el=>{el.disabled=me.role==='leitura'||!st.team||(el.classList.contains('tm')&&!st.days[+el.closest('.day-row').dataset.d].on)});
  $$('#waitBody button, #waitBody input').forEach(el=>el.disabled=me.role==='leitura'||!st.alert);
  if(me.role==='leitura')$$('button,input,select').forEach(el=>el.disabled=true);
  paintBar();
}
function paintBar(){
  const dt=dirty(),bad=hasErr(),s=$("#svS");
  s.className="sv-s"+(bad?" bad":dt?" dirty":"");
  s.textContent=bad?"Há campos para corrigir":dt?"Alterações não salvas":"Tudo salvo";
  $("#save").disabled=!dt||bad||saving||me.role==='leitura';$("#discard").hidden=!dt;
}
const touch=()=>{paintAll()};

/* eventos */
$("#swTeam").onclick=()=>{st.team=!st.team;touch()};
$("#swWait").onclick=()=>{st.alert=!st.alert;touch()};
$("#swPhone").onclick=()=>{if(me.role==='brevia'){st.phone=st.phone==='visible'?'hidden':'visible';touch()}};
$("#tz").onchange=e=>{st.tz=e.target.value;touch()};
$("#sched").addEventListener("click",e=>{const b=e.target.closest(".sw");if(!b)return;const d=+b.closest(".day-row").dataset.d;st.days[d].on=!st.days[d].on;touch()});
$("#sched").addEventListener("input",e=>{
  const i=e.target.closest(".tm");if(!i)return;
  let v=i.value.replace(/[^\d:]/g,"");
  if(/^\d\d$/.test(v)&&e.inputType!=="deleteContentBackward")v+=":";
  i.value=v;st.days[+i.closest(".day-row").dataset.d][i.dataset.k]=v;touch();
});
function norm(v){const d=v.replace(/\D/g,"");if(!d)return v.trim();let h,m;if(d.length<=2){h=d;m="00"}else if(d.length===3){h=d[0];m=d.slice(1)}else{h=d.slice(0,2);m=d.slice(2,4)}return h.padStart(2,"0")+":"+m.padStart(2,"0")}
$("#sched").addEventListener("focusout",e=>{const i=e.target.closest(".tm");if(!i)return;const d=+i.closest(".day-row").dataset.d;st.days[d][i.dataset.k]=norm(i.value);touch()});
$$("[data-preset]").forEach(b=>b.onclick=()=>{
  const p=b.dataset.preset;
  if(p==="com")ORDER.forEach(d=>st.days[d]=d>=1&&d<=5?D(1,"09:00","17:00"):D(0,"08:00","18:00"));
  else if(p==="all")ORDER.forEach(d=>st.days[d]=D(1,"08:00","18:00"));
  else if(p==="24")ORDER.forEach(d=>st.days[d]=D(1,"00:00","24:00"));
  else{const m=st.days[1];if(!m.on||dayErr(1)){toast("Acerte o horário de segunda primeiro.");return}[2,3,4,5].forEach(d=>st.days[d]=D(1,m.s,m.e));toast("Horário de segunda copiado para terça a sexta.")}
  touch();
});
const wset=n=>{st.wait=String(Math.min(120,Math.max(1,n)));touch()};
$("#wMinus").onclick=()=>wset((waitNum()||10)-1);
$("#wPlus").onclick=()=>wset((waitNum()||0)+1);
$("#wait").addEventListener("input",e=>{st.wait=e.target.value.replace(/\D/g,"");e.target.value=st.wait;touch()});
$("#wait").addEventListener("blur",()=>{if(st.alert&&!waitErr())st.wait=String(waitNum());touch()});
$("#waitChips").addEventListener("click",e=>{const b=e.target.closest("[data-w]");if(b)wset(+b.dataset.w)});
$("#modes").addEventListener("change",e=>{if(e.target.name==="mode"){st.mode=e.target.value;legacyClaimed=false;touch()}});
const toPolicy = value => ({hours_enabled:value.team,timezone:value.tz,timeout_enabled:value.alert,timeout_minutes:Number(value.wait)>=1&&Number(value.wait)<=120?Number(value.wait):data.timeout_minutes,timeout_mode:value.mode==='waiting'?'waiting':legacyClaimed?'claimed':'both',phone_consent:value.phone==='consent',phone_visibility:value.phone,
 windows:ORDER.map(d=>{const x=value.days[d];return{weekday:(d+6)%7,enabled:!!x.on,start:okT(x.s,false)?x.s:'08:00',end:okT(x.e,true)?x.e:'18:00'}})});
$('#save').onclick=async()=>{
 if(hasErr()||saving||me.role==='leitura')return;
 const submitted=clone(st),button=$('#save');saving=true;button.textContent='Salvando…';paintBar();
 try{await api('/api/admin/attendance','PUT',toPolicy(submitted));saved=clone(submitted);if(host.isConnected)toast('Regras de atendimento salvas.');}
 catch(error){if(host.isConnected){const status=$('#svS');status.className='sv-s bad';status.textContent=error.message||'Não foi possível salvar. Tente novamente.';}saving=false;button.disabled=false;button.textContent='Salvar regras de atendimento';return;}
 saving=false;button.textContent='Salvar regras de atendimento';if(host.isConnected)paintBar();
};
$("#discard").onclick=()=>{st=clone(saved);touch();toast("Alterações descartadas.")};

buildSched();paintAll();
const timer=setInterval(()=>{if(!host.isConnected||ui.tab!=='attendance'){clearInterval(timer);return;}paintNow();},30000);
}
