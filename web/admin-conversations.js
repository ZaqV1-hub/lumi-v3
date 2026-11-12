const conversationChannel = channel => ({
  whatsapp: 'WhatsApp', instagram: 'Instagram', instagram_comment: 'Comentário Instagram', simulator: 'Simulador',
})[channel] || 'Simulador';
const conversationClock = new Intl.DateTimeFormat('pt-BR', {hour:'2-digit', minute:'2-digit', timeZone:'America/Sao_Paulo'});
const conversationDate = new Intl.DateTimeFormat('pt-BR', {day:'2-digit', month:'long', year:'numeric', timeZone:'America/Sao_Paulo'});
const clockTime = value => value ? conversationClock.format(new Date(value)) : '';
const humanDrafts = new Map();
const sendingHumanReplies = new Set();
let displayedConversation = null;

function renderConvos() {
  const waiting = convos.filter(c => c.status === 'aguardando');
  const scroll = $('.c-items')?.scrollTop || 0;
  const thread = $('.conversations-view .thread');
  const position = thread && {id: displayedConversation, top: thread.scrollTop,
    atEnd: thread.scrollHeight - thread.clientHeight - thread.scrollTop < 60, profile: $('#contactProfile')?.open};
  const focused = document.activeElement;
  const inputId = ['cq', 'humanText'].includes(focused?.id) ? focused.id : '';
  const selection = inputId ? [focused.selectionStart, focused.selectionEnd] : [];
  calling.parkBar();
  $('#content').innerHTML = `<div class="conversations-view">
    <div class="conversation-toolbar"><span>Atendimentos</span><div class="simulation-links">${simulationRoles.map(r => `<a class="btn btn-ghost btn-sm" href="/chat/${encodeURIComponent(me.slug)}?tenant=${encodeURIComponent(me.tenant_id)}&simulation=${encodeURIComponent(r.role)}" target="_blank" rel="noopener">Simular ${esc(r.label)}</a>`).join('')}</div></div>
    ${waiting.length ? `<div class="notice-live" role="status">${waiting.map(c => esc(c.name) + ' pediu atendimento humano.').join(' ')}</div>` : ''}
    <div id="cbody"></div></div>`;
  drawConvoBody(position);
  $('.c-items').scrollTop = scroll;
  const input = inputId && $('#' + inputId);
  if (input) {
    input.focus({preventScroll:true});
    input.setSelectionRange(...selection);
  }
}

function contactLabel(c) {
  const name = c.name === "Nome não informado" && c.contact_id ? "" : '<b>' + esc(c.name) + '</b>';
  const id = c.contact_id ? '<span class="contact-id" aria-label="ID do cliente ' + esc(c.contact_id) + '">#' + esc(c.contact_id) + '</span>' : '';
  return '<span class="contact-label">' + name + id + '</span>';
}

function conversationRow(c) {
  const last = c.messages.at(-1);
  const status = c.blocked ? 'Bloqueado por spam' : statusLabel(c.status);
  return `<button type="button" class="c-item" data-id="${esc(c.id)}" aria-current="${c.id === ui.conv}">
    <span class="top"><span class="pill wa">${conversationChannel(c.channel)}</span><time>${clockTime(last?.created_at || c.created_at)}</time></span>
    ${contactLabel(c)}<span class="last">${esc(last?.content || last?.attachment_name || 'Conversa iniciada')}</span>
    <span class="pill ${c.blocked ? 'topic' : c.status}">${esc(status)}</span></button>`;
}

function drawConvoBody(position) {
  const selectedStatus = {[statusLabel('lumi')]:'lumi','Aguardando atendimento':'aguardando','Atendimento humano':'humano'}[ui.tp];
  const query = ui.q.trim().toLowerCase();
  const idQuery = query.replace(/^#\s*/, '');
  const list = convos.filter(c => (!selectedStatus || c.status === selectedStatus) &&
    (c.name.toLowerCase().includes(query) || (idQuery && [c.contact_id, c.id].some(id => id?.toLowerCase().includes(idQuery)))));
  if (!list.some(c => c.id === ui.conv)) ui.conv = list[0]?.id || '';
  const c = list.find(c => c.id === ui.conv);
  displayedConversation = c?.id;
  const listTop = $('.c-items')?.scrollTop || 0;
  const searchFocused = document.activeElement?.id === 'cq';
  const cursor = searchFocused ? $('#cq').selectionStart : null;
  calling.parkBar();
  $('#cbody').innerHTML = `<section class="card convo ${ui.mobileDetail && c ? 'show-detail' : ''}">
    <div class="c-list">
      <div class="list-heading"><span class="count">${list.length} ${list.length === 1 ? 'atendimento' : 'atendimentos'}</span>
      <div class="conversation-tabs" role="group" aria-label="Filtrar conversas">
        <button type="button" data-filter="" aria-pressed="${!selectedStatus}">Todas</button>
        <button type="button" data-filter="Atendimento humano" aria-pressed="${selectedStatus === 'humano'}">Com atendente</button>
      </div></div>
      <div class="conversation-search">${searchIco}<input class="input" id="cq" aria-label="Buscar por nome ou ID" placeholder="Buscar por nome ou ID" value="${esc(ui.q)}"></div>
      <div class="c-items">${list.map(conversationRow).join('') || '<div class="empty">Nenhuma conversa neste filtro.</div>'}</div>
    </div>
    <div class="c-detail">${c ? conversationDetail(c) : '<div class="empty">Nenhuma conversa selecionada.</div>'}</div>
  </section>`;
  $('.c-items').scrollTop = listTop;
  $('#cq').oninput = event => { ui.q = event.target.value; drawConvoBody(); };
  if (searchFocused) { $('#cq').focus({preventScroll:true}); $('#cq').setSelectionRange(cursor, cursor); }
  document.querySelectorAll('.conversation-tabs button').forEach(button => button.onclick = () => {
    ui.tp = button.dataset.filter;
    drawConvoBody();
    document.querySelector('.conversation-tabs [aria-pressed="true"]')?.focus({preventScroll:true});
  });
  document.querySelectorAll('.c-item').forEach(button => button.onclick = () => {
    ui.conv = button.dataset.id;
    ui.mobileDetail = true;
    drawConvoBody();
  });
  mountCallingControls(c);
  if (!c) return;
  wireConversation(c, position?.id === c.id ? position : null);
}

function wireConversation(c, position) {
  const path = '/api/admin/conversations/' + c.id;
  $('#contactRole').onchange = async event => {
    const field = event.target;
    try {
      await api(path + '/role', 'PUT', {role: field.value});
      await refresh();
      toast('Papel do contato atualizado.');
    } catch (error) { field.value = c.role; toast(error.message); }
  };
  $('.back').onclick = () => { ui.mobileDetail = false; drawConvoBody(); };
  for (const [id, action] of [['take','claim'], ['release','release'], ['unblock','unblock']]) {
    $('#' + id)?.addEventListener('click', async event => {
      const button = event.currentTarget;
      button.disabled = true;
      try { await api(path + '/' + action, 'POST'); await refresh(); }
      catch (error) { toast(error.message); }
      finally { if (button.isConnected && action !== 'release') button.disabled = false; }
      if (button.isConnected && action === 'release') mountCallingControls(c);
    });
  }
  const input = $('#humanText');
  const form = $('#humanForm');
  const draftKey = me.tenant_id + ':' + c.id;
  if (form) {
    input.value = humanDrafts.get(draftKey) || '';
    input.oninput = () => humanDrafts.set(draftKey, input.value);
    input.onkeydown = event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
    };
    const button = form.querySelector('button');
    button.disabled = sendingHumanReplies.has(draftKey);
    form.onsubmit = async event => {
      event.preventDefault();
      const content = input.value.trim();
      if (!content || sendingHumanReplies.has(draftKey)) return;
      sendingHumanReplies.add(draftKey);
      button.disabled = true;
      try {
        await api(path + '/messages', 'POST', {content});
        if (humanDrafts.get(draftKey)?.trim() === content) humanDrafts.delete(draftKey);
        const current = displayedConversation === c.id ? $('#humanText') : null;
        if (current?.value.trim() === content) current.value = '';
        await refresh();
      } catch (error) { toast(error.message); }
      finally {
        sendingHumanReplies.delete(draftKey);
        if (displayedConversation === c.id) {
          const currentButton = $('#humanForm button');
          if (currentButton) currentButton.disabled = false;
        }
      }
    };
  }
  if (position?.profile) $('#contactProfile').open = true;
  const thread = $('.thread');
  const jump = $('#jumpMessages');
  thread.scrollTop = position && !position.atEnd ? position.top : thread.scrollHeight;
  thread.onscroll = () => { jump.hidden = thread.scrollHeight - thread.clientHeight - thread.scrollTop < 60; };
  thread.onscroll();
  jump.onclick = () => { thread.scrollTop = thread.scrollHeight; };
}

function conversationDetail(c) {
  const initials = c.name === 'Nome não informado' ? '#' : c.name.trim().split(/\s+/).slice(0,2).map(word => word[0]).join('').toUpperCase();
  const readonly = me.role === 'leitura';
  const human = c.status === 'humano';
  return `<header class="d-head">
    <div class="d-top">
      <button type="button" class="btn btn-ghost btn-sm back" aria-label="Voltar aos atendimentos">‹</button>
      <span class="ini" aria-hidden="true">${esc(initials)}</span>
      <div class="d-id"><h2>${contactLabel(c)}</h2><p class="d-sub"><b class="${esc(c.status)}">${esc(statusLabel(c.status))}</b><span>${conversationChannel(c.channel)}</span></p></div>
      <div class="handover-actions">
        ${readonly ? '' : human ? '<button class="btn btn-ghost btn-sm" id="release">Devolver à ' + esc(assistantName()) + '</button>' : '<button class="btn btn-primary btn-sm" id="take">Assumir atendimento</button>'}
        ${c.blocked && !readonly ? '<button class="btn btn-danger btn-sm" id="unblock">Desbloquear contato</button>' : ''}
      </div>
    </div>
    ${renderCallingControls(c)}
    ${conversationProfile(c)}
  </header>
  <div id="calling-slot"></div>
  <div class="thread-wrap"><div class="thread" role="log" aria-label="Mensagens da conversa">${conversationMessages(c)}</div><button id="jumpMessages" type="button" hidden>Ir para as últimas mensagens ↓</button></div>
  ${human && !readonly ? `<form id="humanForm" class="reply-box">
    <textarea id="humanText" class="input" rows="1" required aria-label="Sua resposta ao cliente" placeholder="Escreva sua mensagem"></textarea>
    <button type="submit" class="go" aria-label="Enviar mensagem"><svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m2 9 15-6-5 15-3-6-7-3Zm7 3 8-9"/></svg></button>
    <small>Enter para enviar · Shift + Enter para uma nova linha</small>
  </form>` : `<div class="lumi-banner"><b>${readonly ? 'Visualização do atendimento' : esc(statusLabel(c.status))}</b></div>`}`;
}

function conversationProfile(c) {
  const profile = c.profile;
  const status = !profile?.enabled ? '' : profile.completed ? ' · Onboarding concluído' : ' · Onboarding em andamento';
  const roles = contactRoles.filter(r => r.role !== 'administrador' || me.role === 'brevia');
  return `<details id="contactProfile" class="conversation-profile"><summary>Perfil do cliente${status}</summary>
    <div class="meta-panel"><div><label for="contactRole">Papel do contato</label>
      <select class="input" id="contactRole"${['atendente','corretor','leitura'].includes(me.role) ? ' disabled' : ''}>${roles.map(r => `<option value="${esc(r.role)}"${(c.role || 'cliente') === r.role ? ' selected' : ''}>${esc(r.label)}</option>`).join('')}</select></div>
      ${(profile?.fields || []).map(f => `<div><span>${esc(f.title)}</span><b>${esc(f.value || 'Ainda não informado')}</b></div>`).join('')}
    </div></details>`;
}

function conversationMessages(c) {
  let day = '';
  return c.messages.map(m => {
    const date = m.created_at ? conversationDate.format(new Date(m.created_at)) : '';
    const separator = date && date !== day ? `<span class="day">${esc(date)}</span>` : '';
    day = date;
    const kind = {cliente:'in', sistema:'system', humano:'me', lumi:'out'}[m.sender] || 'in';
    const url = m.image_id ? adminPath('/api/admin/images/' + m.image_id + '/file') : m.attachment_url && adminPath(m.attachment_url);
    let media = '';
    if (url && (m.image_id || m.attachment_kind === 'image')) media = `<a href="${esc(url)}" target="_blank" rel="noopener"><img src="${esc(url)}" alt="Imagem da conversa"></a>`;
    if (url && m.attachment_kind === 'audio') media = `<audio controls preload="metadata" src="${esc(url)}"></audio>`;
    if (url && m.attachment_kind === 'video') media = `<video controls preload="metadata" src="${esc(url)}"></video>`;
    if (url && m.attachment_kind === 'document') media = `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(m.attachment_name || 'Documento')}</a>`;
    const delivery = {pending:'Envio pendente',sending:'Enviando à Meta',sent:'Aceito pela Meta',delivered:'Entregue',read:'Lido',failed:'Falha no envio'}[m.delivery];
    const metadata = [clockTime(m.created_at), m.sender === 'lumi' ? assistantName() : '', delivery].filter(Boolean).join(' · ');
    const content = String(m.content || '').split(/(https?:\/\/[^\s<>]+)/g).map(part => {
      if (!/^https?:\/\//.test(part)) return esc(part);
      const link = part.replace(/[.,;!?]+$/, '');
      return `<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(link)}</a>${esc(part.slice(link.length))}`;
    }).join('');
    return `${separator}<div class="msg ${kind}${m.event_kind === 'whatsapp_call' ? ' call-event' : ''}${m.delivery === 'failed' ? ' fail' : ''}">${m.name ? `<strong>${esc(m.name)}</strong>` : ''}
      ${media}<div class="tx">${content}</div><time>${esc(metadata)}${m.delivery_error ? '<br>' + esc(m.delivery_error) : ''}</time></div>`;
  }).join('') || '<div class="empty">Esta conversa ainda não tem mensagens.</div>';
}
