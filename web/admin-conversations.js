const conversationChannel = channel => ({
  whatsapp: 'WhatsApp', whatsapp_flow: 'WhatsApp Flows', instagram: 'Instagram', instagram_comment: 'Comentário Instagram', simulator: 'Simulador',
})[channel] || 'Simulador';
const conversationClock = new Intl.DateTimeFormat('pt-BR', {hour:'2-digit', minute:'2-digit', timeZone:'America/Sao_Paulo'});
const conversationDate = new Intl.DateTimeFormat('pt-BR', {day:'2-digit', month:'long', year:'numeric', timeZone:'America/Sao_Paulo'});
const clockTime = value => value ? conversationClock.format(new Date(value)) : '';
const humanDrafts = new Map();
const sendingHumanReplies = new Set();
let displayedConversation = null;

function renderConvos(prepend = false) {
  const waitingCount = adminWaitingCount;
  const scroll = $('.c-items')?.scrollTop || 0;
  const thread = $('.conversations-view .thread');
  const position = thread && {id: displayedConversation, top: thread.scrollTop,
    atEnd: !prepend && thread.scrollHeight - thread.clientHeight - thread.scrollTop < 60,
    height: prepend ? thread.scrollHeight : null, profile: $('#contactProfile')?.open,
    tools: $('#conversationTools')?.open};
  const focused = document.activeElement;
  const inputId = ['cq', 'humanText'].includes(focused?.id) ? focused.id : '';
  const selection = inputId ? [focused.selectionStart, focused.selectionEnd] : [];
  calling.parkBar();
  $('#content').innerHTML = `<div class="conversations-view">
    <div class="conversation-toolbar"><span>Atendimentos</span><div class="simulation-links">${simulationRoles.map(r => `<a class="btn btn-ghost btn-sm" href="/chat/${encodeURIComponent(me.slug)}?tenant=${encodeURIComponent(me.tenant_id)}&simulation=${encodeURIComponent(r.role)}" target="_blank" rel="noopener">Simular ${esc(r.label)}</a>`).join('')}</div></div>
    ${waitingCount ? `<button type="button" class="btn btn-ghost queue-notice" id="openWaiting">
      ${waitingCount === 1 ? '1 pessoa aguardando atendimento humano' : waitingCount + ' pessoas aguardando atendimento humano'}
      <span aria-hidden="true">→</span></button>` : ''}
    <div id="cbody"></div></div>`;
  drawConvoBody(position);
  $('#openWaiting')?.addEventListener('click', () => setConversationFilter('Aguardando atendimento', true));
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

const visitGoalBadge = c => c.visit_confirmed ? '<span class="pill wa">Visita agendada</span>' : '';

function conversationRow(c) {
  const last = c.last_message;
  const status = c.blocked ? 'Bloqueado por spam' : c.operator_name ? 'Com ' + c.operator_name
    : c.status === 'aguardando' ? 'Aguardando atendimento' : statusLabel(c.status);
  return `<button type="button" class="c-item" data-id="${esc(c.id)}" aria-current="${c.id === ui.conv}">
    <span class="top"><span class="pill wa">${conversationChannel(c.channel)}</span><time>${clockTime(last?.created_at || c.created_at)}</time></span>
    ${contactLabel(c)}<span class="last">${esc(last?.content || last?.attachment_name || 'Conversa iniciada')}</span>
    <span class="conversation-row-status"><span class="pill ${c.blocked ? 'topic' : c.status}">${esc(status)}</span>${visitGoalBadge(c)}</span>
    ${c.waiting_since ? `<small class="queue-request-time">Solicitou atendimento em ${esc(new Date(c.waiting_since).toLocaleString('pt-BR', {timeZone:'America/Sao_Paulo'}))}</small>` : ''}</button>`;
}

function drawConvoBody(position) {
  const selectedStatus = conversationFilter();
  const list = conversationList;
  const c = threadPreview();
  displayedConversation = ui.conv;
  const thread = conversationThread;
  const listTop = $('.c-items')?.scrollTop || 0;
  const searchFocused = document.activeElement?.id === 'cq';
  const cursor = searchFocused ? $('#cq').selectionStart : null;
  calling.parkBar();
  $('#cbody').innerHTML = `<section class="card convo ${ui.mobileDetail && ui.conv ? 'show-detail' : ''}">
    <div class="c-list">
      <div class="list-heading"><span class="count">${list.items ? list.items.length + (list.items.length === 1 ? ' atendimento exibido' : ' atendimentos exibidos') : ''}</span>
      <div class="conversation-tabs" role="group" aria-label="Filtrar conversas">
        <button type="button" data-filter="" aria-pressed="${!selectedStatus}">Todas</button>
        <button type="button" data-filter="Aguardando atendimento" aria-pressed="${selectedStatus === 'aguardando'}">Aguardando</button>
        <button type="button" data-filter="Atendimento humano" aria-pressed="${selectedStatus === 'humano'}">Com atendente</button>
      </div></div>
      <div class="conversation-search">${searchIco}<input class="input" id="cq" aria-label="Buscar por nome ou ID" placeholder="Buscar por nome ou ID" value="${esc(ui.q)}"></div>
      <div class="c-items">${list.items?.map(conversationRow).join('') || ''}
        ${list.items && !list.items.length ? '<div class="empty">Nenhuma conversa neste filtro.</div>' : ''}
        ${list.cursor ? '<div class="page-more"><button type="button" class="btn btn-ghost" id="moreConversations"' + (list.busy ? ' disabled' : '') + '>' + (list.busy ? 'Carregando…' : 'Ver mais contatos') + '</button></div>' : ''}
        <div id="conversationListStatus"></div>
      </div>
    </div>
    <div class="c-detail">${thread?.conversation ? conversationDetail({...c, messages: thread.messages}, position)
      : ui.conv ? '<div id="conversationHistoryStatus"></div>' : '<div class="empty">Nenhuma conversa selecionada.</div>'}</div>
  </section>`;
  $('.c-items').scrollTop = listTop;
  $('#cq').oninput = event => searchConversations(event.target.value);
  if (searchFocused) { $('#cq').focus({preventScroll:true}); $('#cq').setSelectionRange(cursor, cursor); }
  document.querySelectorAll('.conversation-tabs button').forEach(button => {
    button.onclick = () => setConversationFilter(button.dataset.filter);
  });
  document.querySelectorAll('.c-item').forEach(button => {
    button.onclick = () => openConversation(button.dataset.id);
  });
  $('#moreConversations')?.addEventListener('click', () => loadConversationPage({ more: true }));
  if (list.error) {
    adminDataStatus($('#conversationListStatus'), 'Não foi possível carregar os atendimentos.',
                    () => loadConversationPage({ more: Boolean(list.items && list.cursor) }));
  } else if (!list.items) {
    adminDataStatus($('#conversationListStatus'), 'Carregando atendimentos…');
  }
  const historyStatus = $('#conversationHistoryStatus');
  if (historyStatus) {
    if (thread?.error) adminDataStatus(historyStatus, 'Não foi possível carregar a conversa.', loadConversationThread);
    else adminDataStatus(historyStatus, 'Carregando mensagens…');
    historyStatus.insertAdjacentHTML('afterbegin', '<button type="button" class="btn btn-ghost back" aria-label="Voltar aos atendimentos">‹</button>');
    historyStatus.querySelector('.back').onclick = () => { ui.mobileDetail = false; renderConvos(); };
  }
  mountCallingControls(thread?.conversation || null);
  stopOperatorRecordingUnless(c?.can_reply !== false ? c?.id : null);
  if (!thread?.conversation) return;
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
  $('.back').onclick = () => { ui.mobileDetail = false; renderConvos(); };
  $('#moreMessages')?.addEventListener('click', () => loadConversationThread({ older: true }));
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
    const button = form.querySelector('[type="submit"]');
    button.disabled = sendingHumanReplies.has(draftKey);
    mountOperatorMedia(form, c);
    form.onsubmit = async event => {
      event.preventDefault();
      const content = input.value.trim();
      const attachment = await finishOperatorRecording(c.id) || operatorAttachments.get(c.id);
      if (displayedConversation !== c.id || (!content && !attachment) || sendingHumanReplies.has(draftKey)) return;
      sendingHumanReplies.add(draftKey);
      button.disabled = true;
      try {
        if (attachment) {
          await sendOperatorMedia(path, attachment, attachment.kind === 'audio' ? '' : content);
          clearOperatorAttachment(c.id);
          if (attachment.kind === 'audio') {
            await refresh();
            return;
          }
        } else {
          await api(path + '/messages', 'POST', {content});
        }
        if (humanDrafts.get(draftKey)?.trim() === content) humanDrafts.delete(draftKey);
        const current = displayedConversation === c.id ? $('#humanText') : null;
        if (current?.value.trim() === content) current.value = '';
        await refresh();
      } catch (error) { toast(error.message); }
      finally {
        sendingHumanReplies.delete(draftKey);
        if (displayedConversation === c.id) {
          const currentButton = $('#humanForm [type="submit"]');
          if (currentButton) currentButton.disabled = false;
        }
      }
    };
  }
  if (position?.profile) $('#contactProfile').open = true;
  const thread = $('.thread');
  const jump = $('#jumpMessages');
  const addedHeight = position?.height ? thread.scrollHeight - position.height : 0;
  thread.scrollTop = position && !position.atEnd ? position.top + addedHeight : thread.scrollHeight;
  thread.onscroll = () => { jump.hidden = thread.scrollHeight - thread.clientHeight - thread.scrollTop < 60; };
  thread.onscroll();
  jump.onclick = () => { thread.scrollTop = thread.scrollHeight; };
}

function conversationDetail(c, position) {
  const initials = c.name === 'Nome não informado' ? '#' : c.name.trim().split(/\s+/).slice(0,2).map(word => word[0]).join('').toUpperCase();
  const readonly = me.role === 'leitura';
  const human = c.status === 'humano';
  const canReply = human && !readonly && c.can_reply !== false;
  return `<header class="d-head">
    <div class="d-top">
      <button type="button" class="btn btn-ghost btn-sm back" aria-label="Voltar aos atendimentos">‹</button>
      <span class="ini" aria-hidden="true">${esc(initials)}</span>
      <div class="d-id"><h2>${contactLabel(c)}</h2><p class="d-sub"><b class="${esc(c.status)}">${esc(human && c.operator_name ? 'Atendimento com ' + c.operator_name : statusLabel(c.status))}</b><span>${conversationChannel(c.channel)}</span> ${visitGoalBadge(c)}</p></div>
      <div class="handover-actions">
        ${readonly ? '' : human ? (canReply ? '<button class="btn btn-ghost btn-sm" id="release">Devolver à ' + esc(assistantName()) + '</button>' : '') : '<button class="btn btn-primary btn-sm" id="take">Assumir atendimento</button>'}
        ${c.blocked && !readonly ? '<button class="btn btn-danger btn-sm" id="unblock">Desbloquear contato</button>' : ''}
      </div>
    </div>
    <details id="conversationTools" class="conversation-tools" ${(position?.id === c.id ? position.tools : !matchMedia('(max-width: 900px)').matches) ? 'open' : ''}>
    <summary>Dados e ligação</summary>
    ${renderCallingControls(c)}
    ${c.waiting_since ? `<p class="queue-request-time">Atendimento solicitado em ${esc(new Date(c.waiting_since).toLocaleString('pt-BR', {timeZone:'America/Sao_Paulo'}))}</p>` : ''}
    ${c.phone ? `<p>Telefone: <a href="tel:${esc(c.phone)}">${esc(c.phone)}</a></p>` : c.phone_consent === 'pending' ? '<p class="queue-request-time">Telefone: aguardando autorização do cliente</p>' : c.phone_consent === 'declined' ? '<p class="queue-request-time">Telefone: compartilhamento não autorizado</p>' : ''}
    ${conversationProfile(c)}
    </details>
  </header>
  <div id="calling-slot"></div>
  <div class="thread-wrap"><div class="thread" role="log" aria-label="Mensagens da conversa">${conversationThread.cursor ? `<div class="page-more"><button id="moreMessages" class="btn btn-ghost" type="button" ${conversationThread.busy ? 'disabled' : ''}>${conversationThread.busy ? 'Carregando…' : conversationThread.error ? 'Tentar carregar mensagens anteriores novamente' : 'Ver mais mensagens'}</button></div>` : ''}${conversationMessages(c)}</div><button id="jumpMessages" type="button" hidden>Ir para as últimas mensagens ↓</button></div>
  ${canReply ? `<form id="humanForm" class="reply-box">
    ${operatorMediaControls(c)}
    <textarea id="humanText" class="input" rows="1" aria-label="Sua resposta ao cliente" placeholder="Escreva sua mensagem"></textarea>
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
    if (url && (m.image_id || m.attachment_kind === 'image')) media = `<button type="button" class="conversation-photo" aria-label="Ampliar imagem"><img src="${esc(url)}" alt="Imagem da conversa" loading="lazy"></button>`;
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

const conversationPhotoDialog = document.querySelector('#conversationPhotoDialog');
const conversationPhoto = conversationPhotoDialog.querySelector('img');

document.addEventListener('click', event => {
  const button = event.target.closest('.conversation-photo');
  if (!button || conversationPhotoDialog.open) return;
  conversationPhoto.src = button.querySelector('img').src;
  conversationPhotoDialog.showModal();
});
conversationPhotoDialog.addEventListener('click', event => {
  if (event.target === conversationPhotoDialog) conversationPhotoDialog.close();
});
conversationPhotoDialog.addEventListener('close', () => conversationPhoto.removeAttribute('src'));
