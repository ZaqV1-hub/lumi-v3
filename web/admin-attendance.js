async function drawAttendance() {
  const host = $('#cfgBody');
  adminDataStatus(host, 'Carregando regras de atendimento…');
  let data;
  try { data = await api('/api/admin/attendance'); }
  catch { if (host.isConnected) adminDataStatus(host, 'Não foi possível carregar as regras.', drawAttendance); return; }
  if (!host.isConnected || ui.tab !== 'attendance') return;
  const days=['Segunda-feira','Terça-feira','Quarta-feira','Quinta-feira','Sexta-feira','Sábado','Domingo'];
  host.innerHTML=`<form id="attendanceForm" class="card attendance-settings"><div class="card-h"><h2>Atendimento humano</h2><p>A assistente continua atendendo fora do horário. Solicitações são avisadas à equipe na próxima abertura.</p></div><div class="card-b">
  <label><input type="checkbox" name="hours_enabled" ${data.hours_enabled?'checked':''}> Usar horário de atendimento da equipe</label>
  <label>Fuso horário<input class="input" name="timezone" value="${esc(data.timezone)}" required maxlength="80"></label>
  <fieldset><legend>Dias e horários de atendimento</legend>${days.map((day,index)=>{const window=data.windows.find(w=>w.weekday===index);return `<div class="attendance-day"><label><input type="checkbox" name="day${index}" ${window?'checked':''}> ${day}</label><label>Das <input type="time" name="start${index}" value="${window?.start||'08:00'}" aria-label="Início de ${day}"></label><label>Até <input type="time" name="end${index}" value="${window?.end||'18:00'}" aria-label="Fim de ${day}"></label></div>`;}).join('')}</fieldset>
  <label><input type="checkbox" name="timeout_enabled" ${data.timeout_enabled?'checked':''}> Avisar quando não houver resposta de um atendente</label>
  <label>Tempo de espera, em minutos<input class="input" name="timeout_minutes" type="number" min="1" max="120" value="${data.timeout_minutes}" required></label>
  <label>Aplicar o aviso<select class="input" name="timeout_mode"><option value="both">Na fila e após alguém assumir</option><option value="waiting">Somente enquanto aguarda alguém assumir</option><option value="claimed">Somente após alguém assumir</option></select></label>
  <p>Depois do aviso, a solicitação permanece na fila e a assistente continua ajudando. Se o atendente já respondeu e o cliente não voltou a perguntar, não há aviso. Ligações em andamento são preservadas.</p>
  <label><input type="checkbox" name="phone_consent" ${data.phone_consent?'checked':''}> Pedir autorização para exibir o telefone à equipe no WhatsApp</label>
  <p>O cliente escolhe pelos botões da mensagem. O número só aparece no perfil após autorizar. Recusar não impede o atendimento.</p>
  <p role="alert" hidden></p><button class="btn btn-primary" type="submit">Salvar regras de atendimento</button></div></form>`;
  const form=$('#attendanceForm'); form.elements.timeout_mode.value=data.timeout_mode;
  if(me.role==='leitura')form.querySelectorAll('input,select,button').forEach(field=>field.disabled=true);
  form.onsubmit=async event=>{event.preventDefault();const fields=form.elements;const button=form.querySelector('button');button.disabled=true;
    const body={hours_enabled:fields.hours_enabled.checked,timezone:fields.timezone.value.trim(),timeout_enabled:fields.timeout_enabled.checked,
      timeout_minutes:Number(fields.timeout_minutes.value),timeout_mode:fields.timeout_mode.value,phone_consent:fields.phone_consent.checked,
      windows:days.flatMap((_,weekday)=>fields['day'+weekday].checked?[{weekday,start:fields['start'+weekday].value,end:fields['end'+weekday].value}]:[])};
    const error=form.querySelector('[role="alert"]');error.hidden=true;
    try{await api('/api/admin/attendance','PUT',body);toast('Regras de atendimento salvas.');}
    catch(failure){error.textContent=failure.message;error.hidden=false;}finally{button.disabled=false;}
  };
}
