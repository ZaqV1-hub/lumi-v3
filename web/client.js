const managementMode = new URLSearchParams(location.search).get('management') === '1';
const simulationRole = new URLSearchParams(location.search).get('simulation');
const slug = location.pathname.split('/').pop(), key = 'lumi-client-' + slug + (simulationRole ? '-simulation-'+simulationRole : managementMode ? '-management' : '');
function startConversation(name='') {
  const tenant=new URLSearchParams(location.search).get('tenant');
  if(simulationRole)return api('/api/admin/simulations'+(tenant?'?tenant='+encodeURIComponent(tenant):''),'POST',{role:simulationRole,name});
  return api(managementMode?'/api/console/business/chat':'/api/public/'+slug+'/start','POST',managementMode?undefined:{name});
}
let token = sessionStorage.getItem(key), snapshot = '', pending = 0, refreshing = false;
let conversationStatus = 'lumi', blocked = false, scrollAfterSend = false;
const text = $('msg');
const icons = {
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12l16-8-6 17-3-7z"/></svg>',
  mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0014 0v-2M12 19v3M8 22h8"/></svg>',
};
function setNotice(message = '') { $('notice').textContent = message; }
function resizeText() { text.style.height = 'auto'; text.style.height = Math.min(text.scrollHeight, 140) + 'px'; }
function syncComposer() {
  const canSend = !!text.value.trim() || !!pendingAttachment;
  $('go').innerHTML = canSend ? icons.send : icons.mic;
  $('go').setAttribute('aria-label', canSend ? 'Enviar mensagem' : 'Gravar áudio');
  $('go').disabled = !token || mediaBusy; $('attach').disabled = !token || mediaBusy;
  text.disabled = mediaBusy; text.maxLength = pendingAttachment ? 2000 : 10000;
  showTyping(pending > 0 && conversationStatus === 'lumi' && !blocked);
}
async function refresh() {
  if (!token || refreshing) return;
  const current = token; refreshing = true;
  try {
    const data = await api('/api/client/' + current); if (token !== current) return;
    if (data.tenant) $('company').textContent = data.tenant;
    conversationStatus = data.status; blocked = data.blocked;
    $('status').textContent = blocked ? 'Atendimento bloqueado' : {lumi:'Lumi ativa', aguardando:'Aguardando atendente', humano:'Atendimento humano', desativada:'Lumi desativada'}[data.status] || 'Conversa';
    $('status').className = 'pill ' + (data.status === 'lumi' && !blocked ? 'on' : 'hum');
    const json = JSON.stringify(data.messages);
    if (json !== snapshot) { renderConversation(data.messages, scrollAfterSend); snapshot = json; scrollAfterSend = false; }
    syncComposer();
  } catch (error) { if (token === current) setNotice(error.message); }
  finally { refreshing = false; }
}
$('company').textContent = slug; $('startOverlay').hidden = !!token;
$('start').onsubmit = async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try {
    const data = await startConversation($('name').value.trim());
    token = data.token; sessionStorage.setItem(key, token); snapshot = ''; pending = 0;
    $('company').textContent = data.tenant; $('startOverlay').hidden = true; setNotice(); await refresh(); text.focus();
  } catch (error) { setNotice(error.message); }
  finally { button.disabled = false; }
};
async function sendText() {
  const content = text.value.trim(); if (!content || !token) return;
  const current = token; text.value = ''; resizeText(); pending++; scrollAfterSend = true; setNotice(); syncComposer();
  try {
    const data = await api('/api/client/' + current + '/messages', 'POST', {content});
    if (current !== token) return; if (data.blocked) setNotice('Atendimento bloqueado.'); await refresh();
  } catch (error) { if (current === token) { setNotice(error.message); if (!text.value) text.value = content; } }
  finally { if (current === token) { pending--; resizeText(); syncComposer(); } }
}
function submitMessage() { if (pendingAttachment) sendAttachment(); else if (text.value.trim()) sendText(); else startRecording(); }
text.oninput = () => { resizeText(); syncComposer(); };
text.onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (text.value.trim() || pendingAttachment) submitMessage(); } };
$('go').onclick = submitMessage; $('composer').onsubmit = event => { event.preventDefault(); submitMessage(); };
function closeModal() { $('overlay').hidden = true; $('overlay').replaceChildren(); text.focus(); }
function openModal(node) { $('overlay').replaceChildren(node); $('overlay').hidden = false; $('overlay').querySelector('button')?.focus(); }
function previewImage(url) {
  const box = document.createElement('div'); box.className = 'lightbox';
  const image = document.createElement('img'); image.src = url; image.alt = 'Imagem ampliada';
  const close = document.createElement('button'); close.className = 'x'; close.type = 'button'; close.textContent = '×'; close.setAttribute('aria-label', 'Fechar imagem'); close.onclick = closeModal;
  box.append(image, close); openModal(box);
}
$('overlay').onclick = event => { if (event.target === $('overlay')) closeModal(); };
$('fresh').onclick = () => {
  if (mediaBusy) { setNotice('Aguarde o envio do arquivo terminar.'); return; }
  const box = document.createElement('div'); box.className = 'modal'; box.setAttribute('role','dialog'); box.setAttribute('aria-modal','true');
  box.innerHTML = '<h2>Começar uma nova conversa?</h2><p>Um novo contato de teste será criado. O histórico anterior continua disponível no admin.</p><div class="acts"><button class="btn btn-ghost" type="button">Cancelar</button><button class="btn btn-primary" type="button">Nova conversa</button></div>';
  box.querySelector('.btn-ghost').onclick = closeModal;
  box.querySelector('.btn-primary').onclick = async () => {
    cancelAudio(); clearAttachment(); closeModal(); sessionStorage.removeItem(key); token = null;
    snapshot = ''; pending = 0; blocked = false; text.value = ''; thread.replaceChildren();
    if (managementMode || simulationRole) {
      try {
        const data = await startConversation();
        token = data.token; sessionStorage.setItem(key, token); $('startOverlay').hidden = true;
        setNotice(); await refresh(); syncComposer(); text.focus();
      } catch (error) {setNotice(error.message); syncComposer();}
      return;
    }
    $('status').textContent = 'Simulador'; $('startOverlay').hidden = false; setNotice(); resizeText(); syncComposer(); $('name').focus();
  };
  openModal(box);
};
document.addEventListener('keydown', event => { if (event.key === 'Escape') { if (recording) cancelAudio(); else closeModal(); } });
window.addEventListener('DOMContentLoaded', () => { syncComposer(); refresh(); });
setInterval(refresh, 1200);
