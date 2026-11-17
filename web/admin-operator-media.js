const operatorAttachments = new Map();
let operatorRecording = null;
const operatorIcon = path => `<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
const operatorMediaIcons = {
  attach: operatorIcon('<path d="m21 11.5-8.2 8.2a5 5 0 0 1-7.1-7.1l8.5-8.5a3.5 3.5 0 0 1 4.9 4.9l-8.5 8.5a2 2 0 0 1-2.8-2.8L16 6.5"/>'),
  mic: operatorIcon('<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2m-7 9v3m-4 0h8"/>'),
  trash: operatorIcon('<path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5"/>'),
  pause: operatorIcon('<path d="M9 5v14m6-14v14"/>'),
  play: operatorIcon('<path d="m9 5 11 7-11 7z"/>'),
};

function operatorMediaControls(c) {
  if (c.channel === 'instagram_comment') return '';
  return `<div class="operator-attachment-tray" hidden></div>
    <div class="operator-media-tools">
      <input type="file" hidden aria-label="Selecionar anexo" accept="image/jpeg,image/png,image/webp,video/mp4,audio/*${c.channel === 'instagram' ? '' : ',application/pdf'}">
      <button type="button" data-media="attach" aria-label="Anexar arquivo" title="Anexar arquivo">${operatorMediaIcons.attach}</button>
      <button type="button" data-media="mic" aria-label="Gravar áudio" title="Gravar áudio">${operatorMediaIcons.mic}</button>
    </div>`;
}

function clearOperatorAttachment(cid) {
  const attachment = operatorAttachments.get(cid);
  if (attachment) URL.revokeObjectURL(attachment.url);
  operatorAttachments.delete(cid);
  if (displayedConversation === cid && $('#humanForm')) paintOperatorMedia($('#humanForm'), cid);
}

function selectOperatorAttachment(cid, file, kind) {
  clearOperatorAttachment(cid);
  operatorAttachments.set(cid, {file, kind, url: URL.createObjectURL(file), key: crypto.randomUUID()});
}

function paintOperatorMedia(form, cid) {
  const tray = form.querySelector('.operator-attachment-tray');
  if (!tray) return;
  const attachment = operatorAttachments.get(cid), recording = operatorRecording?.cid === cid ? operatorRecording : null;
  form.classList.toggle('is-recording', Boolean(recording));
  tray.hidden = !attachment && !recording;
  if (recording) {
    tray.innerHTML = `<button type="button" aria-label="Descartar gravação">${operatorMediaIcons.trash}</button>
      <span class="record-indicator" role="status">${recording.recorder.state === 'paused' ? 'Áudio pausado' : 'Gravando áudio…'}</span>
      <button type="button" aria-label="${recording.recorder.state === 'paused' ? 'Retomar gravação' : 'Pausar gravação'}">${recording.recorder.state === 'paused' ? operatorMediaIcons.play : operatorMediaIcons.pause}</button>`;
    const [discard, pause] = tray.querySelectorAll('button');
    discard.onclick = () => stopOperatorRecordingUnless(null);
    pause.onclick = () => {
      if (recording.recorder.state === 'paused') recording.recorder.resume(); else recording.recorder.pause();
      paintOperatorMedia(form, cid);
    };
  } else if (attachment) {
    const preview = attachment.kind === 'image' ? `<img alt="Prévia do anexo" src="${attachment.url}">`
      : attachment.kind === 'audio' ? `<audio controls aria-label="Prévia do áudio" src="${attachment.url}"></audio>` : '';
    tray.innerHTML = `${preview}<span>${esc(attachment.file.name)}</span><button type="button" aria-label="Remover anexo">${operatorMediaIcons.trash}</button>`;
    tray.querySelector('button').onclick = () => clearOperatorAttachment(cid);
  } else {
    tray.replaceChildren();
  }
}

function stopOperatorRecordingUnless(cid) {
  const recording = operatorRecording;
  if (!recording || recording.cid === cid) return;
  operatorRecording = null;
  clearTimeout(recording.timer);
  if (recording.recorder.state !== 'inactive') recording.recorder.stop();
  recording.stream.getTracks().forEach(track => track.stop());
  const form = $('#humanForm');
  if (form && displayedConversation === recording.cid) paintOperatorMedia(form, recording.cid);
}

async function finishOperatorRecording(cid) {
  const recording = operatorRecording;
  if (!recording || recording.cid !== cid) return null;
  if (recording.recorder.state !== 'inactive') recording.recorder.stop();
  return recording.result;
}

async function recordOperatorAudio(cid) {
  if (operatorRecording || operatorAttachments.has(cid)) return;
  if (!window.MediaRecorder || !navigator.mediaDevices?.getUserMedia) {
    toast('Abra o painel em HTTPS ou localhost para usar o microfone.');
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio:true});
    const current = $('#humanForm');
    if (displayedConversation !== cid || !current || operatorRecording || operatorAttachments.has(cid)) {
      stream.getTracks().forEach(track => track.stop());
      return;
    }
    const recorder = new MediaRecorder(stream), chunks = [];
    const recording = operatorRecording = {cid, stream, recorder};
    recording.result = new Promise(resolve => {
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        clearTimeout(recording.timer);
        stream.getTracks().forEach(track => track.stop());
        if (operatorRecording !== recording) { resolve(null); return; }
        operatorRecording = null;
        if (chunks.length) selectOperatorAttachment(cid,
          new File(chunks, 'Gravação de áudio', {type:recorder.mimeType || 'audio/webm'}), 'audio');
        if (displayedConversation === cid && $('#humanForm')) paintOperatorMedia($('#humanForm'), cid);
        resolve(operatorAttachments.get(cid) || null);
      };
      recorder.onerror = () => { stopOperatorRecordingUnless(null); resolve(null); toast('Não foi possível gravar o áudio.'); };
    });
    recorder.start();
    recording.timer = setTimeout(() => { if (recorder.state !== 'inactive') recorder.stop(); }, 110000);
    paintOperatorMedia(current, cid);
  } catch {
    stream?.getTracks().forEach(track => track.stop());
    if (operatorRecording?.stream === stream) stopOperatorRecordingUnless(null);
    toast('Não foi possível acessar o microfone.');
  }
}

function mountOperatorMedia(form, c) {
  const tools = form.querySelector('.operator-media-tools');
  if (!tools) return;
  const input = tools.querySelector('input');
  tools.querySelector('[data-media="attach"]').onclick = () => input.click();
  tools.querySelector('[data-media="mic"]').onclick = () => recordOperatorAudio(c.id);
  input.onchange = () => {
    const file = input.files[0];
    input.value = '';
    if (!file) return;
    const kind = file.type.split('/')[0] === 'application' && file.type === 'application/pdf' ? 'document' : file.type.split('/')[0];
    const max = {image:5, audio:12, video:16, document:16}[kind];
    if (!max || (c.channel === 'instagram' && kind === 'document')) { toast('Esse tipo de arquivo não é aceito neste canal.'); return; }
    if (file.size > max * 1024 * 1024) { toast('O arquivo precisa ter até ' + max + ' MB.'); return; }
    selectOperatorAttachment(c.id, file, kind);
    paintOperatorMedia(form, c.id);
    if (kind !== 'audio') form.elements.humanText.focus();
  };
  paintOperatorMedia(form, c.id);
}

async function sendOperatorMedia(path, attachment, caption) {
  if (attachment.caption !== undefined && attachment.caption !== caption) attachment.key = crypto.randomUUID();
  attachment.caption = caption;
  const response = await fetch(adminPath(path + '/operator-attachment'), {method:'POST', body:attachment.file,
    headers:{'Content-Type':attachment.file.type || 'application/octet-stream', 'X-Media-Request':attachment.key,
      'X-Media-Kind':attachment.kind, 'X-Lumi-Caption':encodeURIComponent(caption)}});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Não foi possível enviar o anexo.');
}
