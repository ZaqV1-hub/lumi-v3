const thread = $('thread');
const nearEnd = () => thread.scrollHeight - thread.scrollTop - thread.clientHeight < 100;
let followEnd = true;
function toEnd() { thread.scrollTop = thread.scrollHeight; $('jump').hidden = true; followEnd = true; }
thread.addEventListener('scroll', () => { followEnd = nearEnd(); if (followEnd) $('jump').hidden = true; });
window.addEventListener('resize', () => { if (followEnd) requestAnimationFrame(toEnd); });
$('jump').onclick = toEnd;
function messageNode(message) {
  const row = document.createElement('div');
  row.dataset.key = message.id; row.dataset.signature = JSON.stringify(message);
  if (message.sender === 'sistema') { row.className = 'sys'; row.textContent = message.content; return row; }
  row.className = 'row ' + (message.sender === 'cliente' ? 'me' : 'lumi');
  if (message.sender !== 'cliente') {
    const avatar = document.createElement('div'); avatar.className = 'av mini'; avatar.setAttribute('aria-hidden', 'true');
    avatar.textContent = message.sender === 'humano' ? (message.name || 'A')[0] : 'L'; row.append(avatar);
  }
  const bubble = document.createElement('div'); bubble.className = 'b';
  if (message.name) { const author = document.createElement('strong'); author.textContent = message.name; bubble.append(author); }
  const imageUrl = message.attachment_kind === 'image' ? message.attachment_url : message.image_url;
  if (imageUrl) {
    bubble.classList.add('img');
    const button = document.createElement('button'); button.type = 'button'; button.className = 'pic'; button.setAttribute('aria-label', 'Ampliar imagem');
    const image = document.createElement('img'); image.src = imageUrl; image.alt = 'Imagem da conversa';
    image.onload = () => { if (followEnd) toEnd(); };
    button.append(image); button.onclick = () => previewImage(imageUrl); bubble.append(button);
  }
  if (message.attachment_kind === 'audio' && message.attachment_url) {
    const audio = document.createElement('audio'); audio.controls = true; audio.preload = 'metadata'; audio.src = message.attachment_url; bubble.append(audio);
  }
  if (message.content && !['[Imagem enviada]', '[Áudio enviado]'].includes(message.content)) {
    const content = document.createElement('div'); content.className = 'message-text' + (imageUrl ? ' cap' : '');
    appendMessageText(content, message.content); bubble.append(content);
  }
  if (message.created_at) {
    const time = document.createElement('time'); time.className = 'num'; time.dateTime = message.created_at;
    time.textContent = new Date(message.created_at).toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'}); bubble.append(time);
  }
  row.append(bubble); return row;
}
function renderConversation(items, force = false) {
  const stick = force || nearEnd(), old = new Map([...thread.children].map(node => [node.dataset.key, node]));
  const nodes = []; let lastDay = '';
  for (const item of items) {
    const day = item.created_at ? new Date(item.created_at).toLocaleDateString('pt-BR') : '';
    if (day && day !== lastDay) {
      const key = 'day-' + day, label = old.get(key) || document.createElement('div');
      label.className = 'day'; label.dataset.key = key; label.textContent = day === new Date().toLocaleDateString('pt-BR') ? 'Hoje' : day;
      nodes.push(label); lastDay = day;
    }
    const previous = old.get(item.id);
    nodes.push(previous?.dataset.signature === JSON.stringify(item) ? previous : messageNode(item));
  }
  if (!nodes.length) { const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = 'Envie uma mensagem para começar.'; nodes.push(empty); }
  // Mantém os elementos de áudio e imagem existentes durante o polling.
  let next = thread.firstChild;
  for (const node of nodes) { if (node === next) next = next.nextSibling; else thread.insertBefore(node, next); }
  while (next) { const extra = next; next = next.nextSibling; extra.remove(); }
  if (stick) toEnd(); else { followEnd = false; $('jump').hidden = false; }
}
function showTyping(active) {
  let node = $('typing');
  if (!active) { node?.remove(); return; }
  if (node) return;
  const stick = nearEnd(); node = document.createElement('div'); node.id = 'typing'; node.className = 'row lumi';
  node.innerHTML = '<div class="av mini" aria-hidden="true">L</div><div class="b typing" aria-label="Lumi está respondendo"><i></i><i></i><i></i></div>';
  thread.append(node); if (stick) toEnd();
}
